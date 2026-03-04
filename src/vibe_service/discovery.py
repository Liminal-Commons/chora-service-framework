"""Feature auto-discovery — scan a directory for feature modules.

A feature module is a Python file that exports:
  FEATURE_META: dict  — name, domain, category, description, input_schema (optional)
  handler: async (args: dict) -> Any  — the feature logic

Optional:
  FEATURE_DEPS: list[str]  — dependency names the feature requires
"""

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


@dataclass
class FeatureModule:
    """A discovered feature module."""

    meta: dict[str, Any]
    handler: Any
    deps: list[str] = field(default_factory=list)


def discover_features(directory: str | Path) -> list[FeatureModule]:
    """Scan a directory for feature modules and return them sorted by name.

    Looks for .py files in subdirectories of `directory`. Each subdirectory
    is a domain. Files must export FEATURE_META and handler to be included.

    Modules without FEATURE_META are silently skipped.
    """
    directory = Path(directory)
    modules: list[FeatureModule] = []

    for domain_dir in sorted(directory.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith(("_", ".")):
            continue
        for py_file in sorted(domain_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            mod = _load_feature_module(py_file)
            if mod is not None:
                modules.append(mod)

    modules.sort(key=lambda m: m.meta["name"])
    return modules


def _load_feature_module(path: Path) -> FeatureModule | None:
    """Load a single Python file and extract feature exports."""
    module_name = f"_feature_{path.parent.name}_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        _logger.warning("Failed to load feature module: %s", path, exc_info=True)
        return None

    meta = getattr(module, "FEATURE_META", None)
    handler = getattr(module, "handler", None)

    if meta is None or handler is None:
        return None

    deps = getattr(module, "FEATURE_DEPS", [])

    return FeatureModule(meta=dict(meta), handler=handler, deps=list(deps))
