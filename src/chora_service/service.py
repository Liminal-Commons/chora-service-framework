"""EcosystemService — the one right way to create an ecosystem service.

Creates a dual-protocol server: FastAPI (REST at /api/) + LazyMCPServer (MCP at /mcp).
Both interfaces share the same domain logic layer.
"""

import contextlib
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import FastAPI

from chora_service.auth import make_auth_dependency
from chora_service.config import BaseServiceConfig
from chora_service.errors import error as _error
from chora_service.errors import ok as _ok
from chora_service.health import build_health_router
from chora_service.logging import configure_logging
from chora_service.mcp import LazyMCPServer, ToolHandler


class EcosystemService:
    """Dual-protocol ecosystem service: REST + MCP + Health.

    Usage:
        service = EcosystemService("my-service", Config())

        @service.tool(name="do_thing", ...)
        async def do_thing(args): ...

        @service.api.get("/api/things")
        async def list_things(): ...

        service.run()
    """

    def __init__(self, name: str, config: BaseServiceConfig) -> None:
        self.name = name
        self.config = config
        self._start_time = time.monotonic()

        # MCP layer
        self.mcp = LazyMCPServer(name)

        # Logging
        configure_logging(level=config.log_level, service_name=name)

        # MCP mount (for embedding into FastAPI)
        self._mcp_app, self._session_manager = self.mcp.build_mcp_mount()

        # FastAPI app with lifespan that manages MCP session manager
        @contextlib.asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with self._session_manager.run():
                yield

        self.api = FastAPI(title=name, version=config.service_version, lifespan=lifespan)

        # Mount MCP at /mcp
        self.api.mount("/mcp", self._mcp_app)

        # Health endpoint
        health_router = build_health_router(
            service_name=name,
            service_version=config.service_version,
            tool_count_fn=lambda: self.mcp.tool_count,
            start_time=self._start_time,
        )
        self.api.include_router(health_router)

        # Auth dependency (available for services that want it on their routes)
        self.auth = make_auth_dependency(config.service_key)

    def tool(
        self,
        name: str,
        description: str,
        category: str,
        input_schema: dict[str, Any] | None = None,
        examples: list[str] | None = None,
    ) -> Callable[[ToolHandler], ToolHandler]:
        """Register an MCP tool. Delegates to LazyMCPServer."""
        return self.mcp.tool(
            name=name,
            description=description,
            category=category,
            input_schema=input_schema,
            examples=examples,
        )

    @staticmethod
    def ok(data: Any) -> dict[str, Any]:
        """Standard success response envelope."""
        return _ok(data)

    @staticmethod
    def error(code: str, message: str, details: Any = None) -> dict[str, Any]:
        """Standard error response envelope."""
        return _error(code, message, details)

    def run(self) -> None:
        """Start the dual-protocol server."""
        import uvicorn

        uvicorn.run(self.api, host=self.config.host, port=self.config.port)
