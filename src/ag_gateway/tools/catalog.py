"""Compute the per-request tool catalog as the intersection of bundle tools
and user JWT permissions. Output is a sorted list of "mcp.tool" strings,
joined into AVAILABLE_TOOLS for the sandbox.
"""
from __future__ import annotations

from ag_gateway.prompts.bundle_view import BundleView


def compute_available_tools(view: BundleView, user_permissions: frozenset[str]) -> list[str]:
    """Return ["mcp.tool", ...] for tools whose requires_permissions are satisfied
    by the user. Tools with empty/missing requires_permissions are available to
    any authenticated user (matching lib-agent-prompt v1.0 defaults)."""
    out: list[str] = []
    for mcp, tools in view.services.items():
        for tool in tools:
            required = frozenset(tool.requires_permissions or [])
            if required.issubset(user_permissions):
                out.append(f"{mcp}.{tool.name}")
    return sorted(out)
