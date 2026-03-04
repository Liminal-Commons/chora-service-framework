"""Tests for feature module standard + auto-discovery.

Scenarios from graph:
  scenario:framework:feature-module-exports-meta-and-handler
  scenario:framework:feature-module-with-dependencies
  scenario:framework:auto-discover-features-from-directory
  scenario:framework:server-registers-all-discovered-features
"""

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from vibe_service import BaseServiceConfig, EcosystemService
from vibe_service.discovery import discover_features, FeatureModule


class SvcConfig(BaseServiceConfig):
    model_config = {"env_prefix": "TEST_DISC_"}


@pytest.fixture
def features_dir(tmp_path: Path) -> Path:
    """Create a temporary features/ directory with valid feature modules."""
    # features/graph/list_nodes.py
    graph_dir = tmp_path / "graph"
    graph_dir.mkdir()
    (graph_dir / "__init__.py").write_text("")
    (graph_dir / "list_nodes.py").write_text(textwrap.dedent('''\
        FEATURE_META = {
            "name": "list_nodes",
            "domain": "graph",
            "category": "query",
            "description": "List nodes in the graph",
            "input_schema": {
                "type": "object",
                "properties": {"node_type": {"type": "string"}},
            },
        }

        async def handler(args):
            node_type = args.get("node_type", "all")
            return {"nodes": [f"{node_type}:1", f"{node_type}:2"]}
    '''))
    (graph_dir / "add_node.py").write_text(textwrap.dedent('''\
        FEATURE_META = {
            "name": "add_node",
            "domain": "graph",
            "category": "mutation",
            "description": "Add a node",
            "input_schema": {
                "type": "object",
                "properties": {"node_id": {"type": "string"}},
                "required": ["node_id"],
            },
        }

        async def handler(args):
            return {"node": args["node_id"]}
    '''))

    # features/lifecycle/deploy.py
    lifecycle_dir = tmp_path / "lifecycle"
    lifecycle_dir.mkdir()
    (lifecycle_dir / "__init__.py").write_text("")
    (lifecycle_dir / "deploy.py").write_text(textwrap.dedent('''\
        FEATURE_META = {
            "name": "deploy",
            "domain": "lifecycle",
            "category": "lifecycle",
            "description": "Deploy a service",
        }

        async def handler(args):
            return {"status": "deployed"}
    '''))

    return tmp_path


@pytest.fixture
def features_dir_with_invalid(features_dir: Path) -> Path:
    """Add a module without FEATURE_META to test skip behavior."""
    graph_dir = features_dir / "graph"
    (graph_dir / "utils.py").write_text(textwrap.dedent('''\
        # Utility module — no FEATURE_META, should be skipped
        def helper():
            return 42
    '''))
    return features_dir


class TestFeatureModuleStandard:
    """Scenario: Feature module exports meta and handler.

    Given a feature module at features/graph/list_nodes.py
    Then it exports FEATURE_META as a dict with keys: name, domain, category, description, input_schema
    And it exports an async handler function
    And the module is independently importable without side effects.
    """

    def test_discover_returns_feature_modules(self, features_dir: Path):
        """discover_features returns FeatureModule objects."""
        modules = discover_features(features_dir)
        assert len(modules) == 3

    def test_feature_module_has_meta(self, features_dir: Path):
        """Each FeatureModule has the expected meta keys."""
        modules = discover_features(features_dir)
        for mod in modules:
            assert "name" in mod.meta
            assert "domain" in mod.meta
            assert "category" in mod.meta
            assert "description" in mod.meta

    def test_feature_module_has_handler(self, features_dir: Path):
        """Each FeatureModule has a callable handler."""
        modules = discover_features(features_dir)
        for mod in modules:
            assert callable(mod.handler)

    def test_modules_without_feature_meta_are_skipped(
        self, features_dir_with_invalid: Path
    ):
        """Modules without FEATURE_META are skipped (not errors)."""
        modules = discover_features(features_dir_with_invalid)
        names = [m.meta["name"] for m in modules]
        assert "utils" not in names
        assert len(modules) == 3  # same count as without the invalid module


class TestFeatureModuleWithDeps:
    """Scenario: Feature module with dependencies.

    Given a feature module that declares FEATURE_DEPS
    Then the FeatureModule.deps list is populated.
    """

    def test_feature_deps_captured(self, tmp_path: Path):
        """FEATURE_DEPS is captured when present."""
        domain_dir = tmp_path / "graph"
        domain_dir.mkdir()
        (domain_dir / "__init__.py").write_text("")
        (domain_dir / "query.py").write_text(textwrap.dedent('''\
            FEATURE_META = {
                "name": "query",
                "domain": "graph",
                "category": "query",
                "description": "Query the graph",
            }
            FEATURE_DEPS = ["graph", "config"]

            async def handler(args):
                return {}
        '''))
        modules = discover_features(tmp_path)
        assert len(modules) == 1
        assert modules[0].deps == ["graph", "config"]

    def test_no_deps_defaults_to_empty(self, features_dir: Path):
        """Modules without FEATURE_DEPS have empty deps list."""
        modules = discover_features(features_dir)
        for mod in modules:
            assert mod.deps == []


class TestAutoDiscovery:
    """Scenario: Auto-discover features from directory.

    Given a features/ directory with modules
    When discover_features is called
    Then it discovers across subdirectories.
    """

    def test_discovers_across_domain_directories(self, features_dir: Path):
        """Features from graph/ and lifecycle/ are both discovered."""
        modules = discover_features(features_dir)
        domains = {m.meta["domain"] for m in modules}
        assert "graph" in domains
        assert "lifecycle" in domains

    def test_discovery_returns_sorted_by_name(self, features_dir: Path):
        """Features are returned sorted by name for deterministic ordering."""
        modules = discover_features(features_dir)
        names = [m.meta["name"] for m in modules]
        assert names == sorted(names)


class TestServerRegistersDiscoveredFeatures:
    """Scenario: Server registers all discovered features.

    Given an EcosystemService with feature() support
    And a features/ directory with 3 valid feature modules
    When discover_and_register is called
    Then all 3 are registered as both MCP tools and REST endpoints
    And health reports tool_count: 3.
    """

    @pytest.fixture
    def service_with_features(self, features_dir: Path) -> EcosystemService:
        config = SvcConfig(service_version="0.1.0")
        svc = EcosystemService("test-discovery", config)
        modules = discover_features(features_dir)
        for mod in modules:
            svc.feature(
                handler=mod.handler,
                **mod.meta,
            )
        return svc

    @pytest.fixture
    async def client(self, service_with_features: EcosystemService):
        transport = ASGITransport(app=service_with_features.api)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c

    async def test_all_features_registered_as_mcp(
        self, service_with_features: EcosystemService
    ):
        result = await service_with_features.mcp._meta_discover({})
        data = json.loads(result)
        names = {t["name"] for t in data["tools"]}
        assert names == {"list_nodes", "add_node", "deploy"}

    async def test_all_features_registered_as_rest(self, client: AsyncClient):
        # Each feature should have a REST endpoint with valid args
        cases = [
            ("/api/graph/list_nodes", {}),
            ("/api/graph/add_node", {"node_id": "test:1"}),
            ("/api/lifecycle/deploy", {}),
        ]
        for path, body in cases:
            resp = await client.post(path, json=body)
            assert resp.status_code == 200, f"Failed: {path}"

    async def test_health_reports_correct_tool_count(self, client: AsyncClient):
        resp = await client.get("/health")
        data = resp.json()
        assert data["tools"] == 3

    async def test_mcp_and_rest_produce_same_result(
        self, service_with_features: EcosystemService, client: AsyncClient
    ):
        """Both protocols return the same data for the same input."""
        mcp_result = await service_with_features.mcp._meta_invoke(
            {"tool_name": "list_nodes", "arguments": {"node_type": "Service"}}
        )
        rest_resp = await client.post(
            "/api/graph/list_nodes", json={"node_type": "Service"}
        )
        assert json.loads(mcp_result)["data"] == rest_resp.json()["data"]
