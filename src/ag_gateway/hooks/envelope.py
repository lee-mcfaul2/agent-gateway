from __future__ import annotations

from typing import Any


def wrap_success(
    payload: Any, *, mcp: str, tool: str, request_uuid: str
) -> dict[str, Any]:
    """Wrap a successful MCP response as a tool-role message body."""
    return {
        "tool_result": {
            "ok": True,
            "mcp": mcp,
            "tool": tool,
            "request_uuid": request_uuid,
            "data": payload,
        }
    }


def wrap_error(
    error: str,
    reason: str,
    *,
    mcp: str,
    tool: str,
    request_uuid: str,
) -> dict[str, Any]:
    """Wrap an error as a tool-role message body."""
    return {
        "tool_result": {
            "ok": False,
            "mcp": mcp,
            "tool": tool,
            "request_uuid": request_uuid,
            "error": error,
            "reason": reason,
        }
    }
