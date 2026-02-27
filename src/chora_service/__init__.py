"""chora-service-framework — shared framework for chora ecosystem services.

Every ecosystem service uses EcosystemService as its entry point:

    from chora_service import EcosystemService, BaseServiceConfig

    class Config(BaseServiceConfig):
        model_config = {"env_prefix": "MY_SERVICE_"}

    service = EcosystemService("my-service", Config())

    @service.tool(name="do_thing", description="...", category="ops", input_schema={...})
    async def do_thing(args: dict) -> str:
        return service.ok(await domain.do_thing(args["param"]))

    @service.api.get("/api/things")
    async def list_things():
        return service.ok(await domain.list_things())

    if __name__ == "__main__":
        service.run()
"""

from chora_service.config import BaseServiceConfig
from chora_service.mcp import ResilientSessionManager
from chora_service.service import EcosystemService

__all__ = ["EcosystemService", "BaseServiceConfig", "ResilientSessionManager"]
