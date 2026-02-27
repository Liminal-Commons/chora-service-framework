"""Standard response envelope for ecosystem services.

Success: {"success": true, "data": <payload>}
Error:   {"success": false, "error": {"code": "<CODE>", "message": "...", "details": ...}}
"""

from typing import Any


def ok(data: Any) -> dict[str, Any]:
    """Standard success response."""
    return {"success": True, "data": data}


def error(code: str, message: str, details: Any = None) -> dict[str, Any]:
    """Standard error response."""
    err: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        err["details"] = details
    return {"success": False, "error": err}
