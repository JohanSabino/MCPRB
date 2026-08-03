"""Motor Python del flujo DANA EPM MVP2.

No contiene secretos ni depende de Rocketbot. Los nombres de configuración
mantienen los de la base para facilitar la migración.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


class WorkflowError(RuntimeError):
    pass


@dataclass
class RunState:
    error_code: str = ""
    error_message: str = ""
    http_status: int | None = None
    downloaded: list[Path] = field(default_factory=list)
    failed_downloads: list[Any] = field(default_factory=list)


@dataclass
class Settings:
    values: dict[str, Any]

    @classmethod
    def from_json(cls, path: Path) -> "Settings":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    @property
    def token(self) -> str:
        return str(
            os.getenv("DANA_API_TOKEN")
            or self.get("ApiToken")
            or self.get("Token")
            or ""
        )

    def endpoint(self, key: str, **replacements: Any) -> str:
        value = str(self.get(key, ""))
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, str(replacement))
        return value


class HttpClient:
    def __init__(self, dry_run: bool = False, timeout: int = 30) -> None:
        self.dry_run = dry_run
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        body: Any = None,
        token: str = "",
    ) -> tuple[int, Any]:
        if not url:
            raise WorkflowError(f"Falta endpoint para {method}")
        if self.dry_run:
            print(f"[DRY-RUN] {method} {url}")
            return 200, None

        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return response.status, self._decode(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            return exc.code, self._decode(raw)
        except urllib.error.URLError as exc:
            raise WorkflowError(f"Error de red en {method} {url}: {exc.reason}") from exc

    def download(self, url: str, destination: Path, token: str = "") -> int:
        if self.dry_run:
            print(f"[DRY-RUN] GET {url} -> {destination}")
            return 200
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(response.read())
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
        except urllib.error.URLError as exc:
            raise WorkflowError(f"Error descargando {url}: {exc.reason}") from exc

    @staticmethod
    def _decode(raw: str) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw


class SapAutomation:
    """Punto único para reemplazar los módulos de UI SAP de Rocketbot."""

    def login(self) -> None:
        raise WorkflowError(
            "SAP aún no está conectado al motor Python: faltan los selectores "
            "SAP GUI/SAP GUI Scripting del proyecto original."
        )

    def process(self, action: int, difference: Mapping[str, Any], txt_path: Path) -> dict[str, Any]:
        raise WorkflowError(
            f"Automatización SAP pendiente para acción {action}; archivo fuente: {txt_path}"
        )


class DanaMvp2:
    def __init__(
        self,
        settings: Settings,
        *,
        dry_run: bool = False,
        http: HttpClient | None = None,
        sap: SapAutomation | None = None,
    ) -> None:
        self.settings = settings
        self.dry_run = dry_run
        self.http = http or HttpClient(dry_run=dry_run)
        self.sap = sap or SapAutomation()
        self.state = RunState()
        self.robot_name = "EPM_DanaMVP2"
        self.trace_dir = Path(
            os.getenv("DANA_TRACE_DIR")
            or settings.get("RutaTrazabilidad")
            or "trazabilidad"
        )
        self.shared_dir = Path(
            os.getenv("DANA_SHARED_DIR")
            or settings.get("RutaCompartida")
            or "salida"
        )

    def run(self) -> RunState:
        try:
            self.prepare()
            self.notify("Inicio de ejecución", "Se inicia el procesamiento de DANA MVP2", "0000FF")
            if not self.dry_run:
                self.sap.login()
            queue = self.get_queue()
            self.download_queue(queue)
            for item in queue:
                self.process_queue_item(item)
            self.copy_trace()
            self.notify("Finaliza ejecución", "Se finaliza el procesamiento de DANA MVP2", "008000")
        except Exception as exc:
            self.state.error_code = self.state.error_code or "FallaEjecucionMVP2"
            self.state.error_message = str(exc)
            self.notify("Error en operaciones de DANA", self.state.error_message, "FF0000")
            if not self.dry_run:
                raise
        return self.state

    def prepare(self) -> None:
        if self.settings.get("LimpiarTrazabilidad", False):
            for child in self.trace_dir.glob("*"):
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def get_queue(self) -> list[dict[str, Any]]:
        status, data = self.http.request(
            "GET", self.settings.endpoint("EndPoint_ColaDeTrabajo"), token=self.settings.token
        )
        self.state.http_status = status
        if status not in (200, 201):
            raise WorkflowError(f"API 01 cola de trabajo respondió {status}: {data}")
        queue = self._as_list(data)
        if not queue and not self.dry_run:
            raise WorkflowError("No existen datos en la cola de trabajo")
        return queue

    def download_queue(self, queue: list[dict[str, Any]]) -> None:
        endpoint = self.settings.endpoint("EndPoint_ObtenerArchivo")
        for item in queue:
            file_id = item.get("id")
            fecha = self._date_folder(item.get("fechaInicio"))
            folder = f"{item.get('rutaSalida', 'sin_ruta')}_{fecha}"
            filename = Path(str(item.get("nombre", f"{file_id}.txt"))).name
            destination = self.trace_dir / folder / filename
            status = self.http.download(f"{endpoint}{file_id}", destination, self.settings.token)
            if status == 200:
                self.state.downloaded.append(destination)
                item["UbicacionTxt"] = str(destination)
            else:
                self.state.failed_downloads.append(file_id)
        if self.state.failed_downloads:
            self.state.error_code = "FallaDescargarArchivoTxt"
            raise WorkflowError(f"No se descargaron: {self.state.failed_downloads}")

    def process_queue_item(self, item: Mapping[str, Any]) -> None:
        differences = item.get("diferencias") or []
        for difference in differences:
            try:
                self.process_difference(item, difference)
            except Exception as exc:
                self.state.error_code = "FallaProcesamientoDiferencia"
                self.state.error_message = str(exc)
                self.update_difference(difference, success=False)
                if not self.dry_run:
                    raise

    def process_difference(self, item: Mapping[str, Any], difference: Mapping[str, Any]) -> None:
        action = int(difference.get("accion", 0))
        txt_path = Path(str(item.get("UbicacionTxt", "")))
        if self.dry_run:
            print(f"[DRY-RUN] diferencia={difference.get('id')} acción={action}")
        else:
            if action == 1:
                self.apply_payment(difference)
            elif action == 2:
                self.cancel_payment(difference)
            elif action == 3:
                self.remesa(difference)
                self.sap.process(action, difference, txt_path)
                self.apply_payment(difference)
            else:
                raise WorkflowError(f"Acción no soportada: {action}")
            self.consult_contract(difference)
            self.bitacora(item, difference)
        self.update_difference(difference, success=True)

    def apply_payment(self, difference: Mapping[str, Any]) -> None:
        url = self.settings.endpoint(
            "EndPoint_AplicarPago",
            NUMERO_APLICACION_PAGO=difference.get("numeroAplicacionPago", self.settings.get("NumeroAplicacionPago", "")),
        )
        body = [{
            "IdTransaccion": difference.get("id"),
            "FechaHora": difference.get("fechaHora"),
            "Fuente": difference.get("fuente"),
            "Correlativo": difference.get("correlativo"),
            "MontoEfectivo": self._decimal(difference.get("banco_Efectivo")),
            "MontoCheque": self._decimal(difference.get("banco_ChequesOB")),
            "MontoExencionIVA": self._decimal(difference.get("banco_ExencionIVA")),
            "TipoDocumento": difference.get("tipoDoc"),
            "NumeroDocumento": difference.get("factura"),
            "TipoIngreso": difference.get("tipoIngresoApiPagos", self.settings.get("TipoIngresoApiPagos")),
        }]
        self._expect_success("POST", url, body, "FallaApiPagos")

    def cancel_payment(self, difference: Mapping[str, Any]) -> None:
        body = {
            "ReferenciaBancos": difference.get("factura"),
            "Importe": difference.get("mQ_Total"),
            "Serie": difference.get("serie"),
            "Contrato": difference.get("correlativo"),
            "Fuente": difference.get("fuente"),
        }
        self._expect_success(
            "DELETE", self.settings.endpoint("EndPoint_AnulacionPago"), body, "FallaApiAnulacion"
        )

    def remesa(self, difference: Mapping[str, Any]) -> Any:
        url = self.settings.endpoint(
            "EndPoint_PagoRemesas",
            TIPO_DOCUMENTO=difference.get("tipoDoc", ""),
            FACTURA=difference.get("factura", ""),
        )
        status, data = self.http.request("GET", url, token=self.settings.token)
        if status not in (200, 201):
            raise WorkflowError(f"FallaAPI_Remesa ({status}): {data}")
        return data

    def consult_contract(self, difference: Mapping[str, Any]) -> Any:
        url = self.settings.endpoint(
            "EndPoint_ConsultaDeContrato", CORRELATIVO=difference.get("correlativo", "")
        )
        status, data = self.http.request("GET", url, token=self.settings.token)
        if status not in (200, 201):
            raise WorkflowError(f"Falla consulta de contrato ({status}): {data}")
        return data

    def bitacora(self, item: Mapping[str, Any], difference: Mapping[str, Any]) -> Any:
        action = int(difference.get("accion", 0))
        prefix = "PyR" if action in (1, 3) else ""
        replace = lambda key: self.settings.get(f"{key}{prefix}")
        body = {
            "Contrato": difference.get("correlativo"),
            "Clase": replace("Clase1"),
            "Accion": replace("Accion"),
            "MedioContacto": replace("Clase2"),
            "Prioridad": replace("Prioridad"),
            "Direccion": replace("SalienEntran"),
            "CreadoPor": self.robot_name,
            "Cuerpo": replace("ES"),
            "InfoCliente": replace("InfoCliente"),
            "DocAdicional": replace("DocAdicional"),
        }
        return self._expect_success(
            "POST", self.settings.endpoint("EndPoint_Bitacora"), body, "FallaApiBitacora"
        )

    def update_difference(self, difference: Mapping[str, Any], success: bool) -> Any:
        url = self.settings.endpoint(
            "EndPoint_ActualizarEstadoDiferencias", ID_DIFERENCIA=difference.get("id", "")
        )
        observation = self.settings.get("ActualizarEstadoDifernciaCasoExitoso", "")
        if not success:
            observation = f"{self.state.error_message} - {self.settings.get('ES', '')}"[:299]
        body = {"DanaObservaciones": observation, "DanaOperado": success}
        return self._expect_success("PATCH", url, body, "Falla_API_ActualizarEstadoDiferencia")

    def copy_trace(self) -> None:
        destination = self.shared_dir / self.robot_name / datetime.now().strftime("%Y/%m/%d")
        if self.dry_run:
            print(f"[DRY-RUN] copiar trazabilidad -> {destination}")
            return
        for source in self.trace_dir.rglob("*"):
            if source.is_file():
                target = destination / source.relative_to(self.trace_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

    def notify(self, title: str, message: str, color: str) -> None:
        url = self.settings.endpoint("EndPoint_NotificacionWebHook")
        if not url:
            return
        body = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": color,
            "summary": title,
            "sections": [{"activityTitle": title, "facts": [{"name": "Registro", "value": message}]}],
        }
        self.http.request("POST", url, body)

    def _expect_success(self, method: str, url: str, body: Any, code: str) -> Any:
        status, data = self.http.request(method, url, body)
        self.state.http_status = status
        if status not in (200, 201, 204):
            self.state.error_code = code
            raise WorkflowError(f"{code} ({status}): {data}")
        return data

    @staticmethod
    def _as_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "result", "items", "colaTrabajo"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        return []

    @staticmethod
    def _date_folder(value: Any) -> str:
        try:
            return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return "S_F"

    @staticmethod
    def _decimal(value: Any) -> Any:
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            return value


def self_check() -> None:
    settings = Settings({"EndPoint_AplicarPago": "https://example.test/pago/NUMERO_APLICACION_PAGO"})
    assert settings.endpoint("EndPoint_AplicarPago", NUMERO_APLICACION_PAGO=7).endswith("/7")
    assert DanaMvp2._date_folder("2026-06-23T07:47:02") == "2026-06-23"
    assert DanaMvp2._date_folder("no-date") == "S_F"


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta el flujo Python de DANA EPM MVP2")
    parser.add_argument("--config", type=Path, required=False)
    parser.add_argument("--execute", action="store_true", help="habilita APIs y SAP; por defecto dry-run")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
        print("self-check ok")
        return
    if not args.config:
        parser.error("--config es obligatorio salvo con --self-check")
    state = DanaMvp2(Settings.from_json(args.config), dry_run=not args.execute).run()
    print(json.dumps({"error_code": state.error_code, "downloaded": [str(p) for p in state.downloaded]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
