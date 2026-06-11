from __future__ import annotations

import asyncio
import json
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self, command: str, args: list[str], env: dict[str, str] | None = None):
        self.command = command
        self.args = args
        self.env = env
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()

    async def connect(self) -> None:
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env,
        )
        stdio, write = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
        await self.session.initialize()

    async def close(self) -> None:
        await self.exit_stack.aclose()
        self.session = None

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def _require_session(self) -> ClientSession:
        if self.session is None:
            raise RuntimeError("Cliente MCP no conectado")
        return self.session

    async def list_tools(self) -> list[types.Tool]:
        result = await self._require_session().list_tools()
        return result.tools

    async def list_resources(self) -> list[types.Resource]:
        result = await self._require_session().list_resources()
        return result.resources

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        return await self._require_session().call_tool(name, arguments)

    async def read_resource(self, uri: str) -> Any:
        result = await self._require_session().read_resource(uri)
        if not result.contents:
            return None
        first = result.contents[0]
        if isinstance(first, types.TextResourceContents):
            mime = (first.mimeType or "").lower()
            text = first.text or ""
            if mime == "application/json":
                return json.loads(text)
            return text
        return first


async def main() -> None:
    command = sys.executable
    args = ["mcp_server.py"]

    async with MCPClient(command, args) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()

        print("Tools:")
        for tool in tools:
            print(f"- {tool.name}")

        print("\nResources:")
        for resource in resources:
            print(f"- {resource.uri}")

        print("\nrocketbot://paths")
        print(await client.read_resource("rocketbot://paths"))


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
