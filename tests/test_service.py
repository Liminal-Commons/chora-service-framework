"""Tests for EcosystemService — dual-protocol creation and wiring."""

import json

import pytest
from httpx import ASGITransport, AsyncClient

from chora_service import BaseServiceConfig, EcosystemService


class SvcConfig(BaseServiceConfig):
    model_config = {"env_prefix": "TEST_SVC_"}


@pytest.fixture
def service() -> EcosystemService:
    config = SvcConfig(service_version="0.1.0")
    svc = EcosystemService("test-svc", config)

    @svc.tool(
        name="greet",
        description="Say hello",
        category="test",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    )
    async def greet(args: dict) -> str:
        return json.dumps(svc.ok(f"Hello, {args['name']}!"))

    @svc.api.get("/api/greet/{name}")
    async def api_greet(name: str):
        return svc.ok(f"Hello, {name}!")

    return svc


@pytest.fixture
async def client(service: EcosystemService):
    transport = ASGITransport(app=service.api)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealth:
    async def test_health_returns_standard_shape(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "test-svc"
        assert data["version"] == "0.1.0"
        assert isinstance(data["tools"], int)
        assert isinstance(data["uptime"], float)

    async def test_health_tool_count_reflects_registered_tools(self, client: AsyncClient):
        resp = await client.get("/health")
        data = resp.json()
        assert data["tools"] == 1  # greet tool


class TestRESTEndpoints:
    async def test_rest_route_returns_ok_envelope(self, client: AsyncClient):
        resp = await client.get("/api/greet/World")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"] == "Hello, World!"


class TestMCPTools:
    async def test_mcp_tool_invocation(self, service: EcosystemService):
        result = await service.mcp._meta_invoke(
            {"tool_name": "greet", "arguments": {"name": "Agent"}}
        )
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"] == "Hello, Agent!"

    async def test_mcp_discover_tools(self, service: EcosystemService):
        result = await service.mcp._meta_discover({})
        data = json.loads(result)
        assert data["server"] == "test-svc"
        assert data["total_tools"] == 1
        assert data["tools"][0]["name"] == "greet"

    async def test_mcp_missing_required_args(self, service: EcosystemService):
        result = await service.mcp._meta_invoke(
            {"tool_name": "greet", "arguments": {}}
        )
        data = json.loads(result)
        assert "error" in data
        assert "name" in data["error"]


class TestErrorEnvelope:
    def test_ok_shape(self, service: EcosystemService):
        result = service.ok({"id": "123"})
        assert result == {"success": True, "data": {"id": "123"}}

    def test_error_shape(self, service: EcosystemService):
        result = service.error("NOT_FOUND", "Circle not found")
        assert result == {
            "success": False,
            "error": {"code": "NOT_FOUND", "message": "Circle not found"},
        }

    def test_error_with_details(self, service: EcosystemService):
        result = service.error("VALIDATION", "Bad input", details={"field": "name"})
        assert result["success"] is False
        assert result["error"]["details"] == {"field": "name"}
