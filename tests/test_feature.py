"""Tests for service.feature() — dual-protocol feature registration.

Scenarios from graph:
  scenario:framework:register-dual-protocol-feature
  scenario:framework:rest-endpoint-receives-json-body-as-args-dict
"""

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from vibe_service import BaseServiceConfig, EcosystemService, ServiceError


class SvcConfig(BaseServiceConfig):
    model_config = {"env_prefix": "TEST_FEAT_"}


@pytest.fixture
def service() -> EcosystemService:
    config = SvcConfig(service_version="0.1.0")
    svc = EcosystemService("test-features", config)

    @svc.feature(
        name="list_nodes",
        domain="graph",
        category="query",
        description="List nodes in the graph",
        input_schema={
            "type": "object",
            "properties": {
                "node_type": {"type": "string"},
            },
        },
    )
    async def list_nodes(args: dict[str, Any]) -> dict[str, Any]:
        node_type = args.get("node_type", "all")
        return {"nodes": [f"{node_type}:1", f"{node_type}:2"]}

    @svc.feature(
        name="add_node",
        domain="graph",
        category="mutation",
        description="Add a node to the graph",
        input_schema={
            "type": "object",
            "properties": {
                "node_type": {"type": "string"},
                "node_id": {"type": "string"},
            },
            "required": ["node_type", "node_id"],
        },
    )
    async def add_node(args: dict[str, Any]) -> dict[str, Any]:
        if not args.get("node_id"):
            raise ServiceError("VALIDATION", "node_id is required")
        return {"node": {"id": args["node_id"], "type": args["node_type"]}}

    return svc


@pytest.fixture
async def client(service: EcosystemService):
    transport = ASGITransport(app=service.api)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestDualProtocolRegistration:
    """Scenario: Register dual-protocol feature.

    Given an EcosystemService instance
    When service.feature(...) is called
    Then the handler is registered as MCP tool
    And the handler is registered as REST POST endpoint at /api/{domain}/{name}
    And both protocols invoke the same handler function.
    """

    async def test_feature_registers_mcp_tool(self, service: EcosystemService):
        """MCP tool is discoverable after service.feature() call."""
        result = await service.mcp._meta_discover({})
        data = json.loads(result)
        tool_names = [t["name"] for t in data["tools"]]
        assert "list_nodes" in tool_names
        assert "add_node" in tool_names

    async def test_feature_mcp_invocation(self, service: EcosystemService):
        """MCP tool invocation works and returns ok envelope."""
        result = await service.mcp._meta_invoke(
            {"tool_name": "list_nodes", "arguments": {"node_type": "Feature"}}
        )
        data = json.loads(result)
        assert data["success"] is True
        assert data["data"]["nodes"] == ["Feature:1", "Feature:2"]

    async def test_feature_registers_rest_endpoint(self, client: AsyncClient):
        """REST POST endpoint exists at /api/{domain}/{name}."""
        resp = await client.post(
            "/api/graph/list_nodes",
            json={"node_type": "Feature"},
        )
        assert resp.status_code == 200

    async def test_feature_mcp_has_correct_category(self, service: EcosystemService):
        """MCP tool has the category from feature registration."""
        result = await service.mcp._meta_discover({})
        data = json.loads(result)
        tools_by_name = {t["name"]: t for t in data["tools"]}
        assert tools_by_name["list_nodes"]["category"] == "query"
        assert tools_by_name["add_node"]["category"] == "mutation"

    async def test_both_protocols_same_handler(self, service: EcosystemService, client: AsyncClient):
        """Both MCP and REST invoke the same handler, producing identical data."""
        # MCP path
        mcp_result = await service.mcp._meta_invoke(
            {"tool_name": "list_nodes", "arguments": {"node_type": "Service"}}
        )
        mcp_data = json.loads(mcp_result)

        # REST path
        rest_resp = await client.post(
            "/api/graph/list_nodes",
            json={"node_type": "Service"},
        )
        rest_data = rest_resp.json()

        # Both should have the same data payload
        assert mcp_data["data"] == rest_data["data"]

    async def test_feature_counted_in_health(self, client: AsyncClient):
        """Features are counted in the health endpoint tool count."""
        resp = await client.get("/health")
        data = resp.json()
        assert data["tools"] == 2  # list_nodes + add_node


class TestRESTEndpointReceivesJsonBody:
    """Scenario: REST endpoint receives JSON body as args dict.

    Given a feature registered with service.feature(...)
    When a POST request is sent to /api/{domain}/{name} with JSON body
    Then the handler receives the JSON body as args dict
    And the response is wrapped in the standard ok envelope.
    """

    async def test_rest_passes_json_body_as_args(self, client: AsyncClient):
        """POST JSON body is passed to handler as args dict."""
        resp = await client.post(
            "/api/graph/add_node",
            json={"node_type": "Feature", "node_id": "feature:test:one"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["node"]["id"] == "feature:test:one"
        assert data["data"]["node"]["type"] == "Feature"

    async def test_rest_ok_envelope_shape(self, client: AsyncClient):
        """REST response follows the standard ok envelope."""
        resp = await client.post(
            "/api/graph/list_nodes",
            json={"node_type": "Term"},
        )
        data = resp.json()
        assert "success" in data
        assert data["success"] is True
        assert "data" in data

    async def test_rest_service_error_returns_error_envelope(self, client: AsyncClient):
        """ServiceError from handler returns error envelope via REST."""
        resp = await client.post(
            "/api/graph/add_node",
            json={"node_type": "Feature", "node_id": ""},
        )
        data = resp.json()
        assert data["success"] is False
        assert data["error"]["code"] == "VALIDATION"
        assert data["error"]["message"] == "node_id is required"

    async def test_rest_empty_body_passes_empty_dict(self, client: AsyncClient):
        """POST with empty/no body passes empty dict as args."""
        resp = await client.post(
            "/api/graph/list_nodes",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # Default node_type is "all" when not provided
        assert data["data"]["nodes"] == ["all:1", "all:2"]
