from __future__ import annotations

from typing import Any

from ag_gateway.hooks.auth_oidc import UserClaims
from ag_gateway.hooks.opa_client import Decision, OPAClient
from ag_gateway.obs.metrics import OPA_DENIALS_TOTAL


def build_input(
    user: UserClaims, mcp: str, tool: str, args: dict[str, Any], request_uuid: str
) -> dict[str, Any]:
    """Construct the OPA input document. Keep field names stable; Rego policies depend on them."""
    return {
        "user": {
            "sub": user.sub,
            "groups": list(user.groups),
            "permissions": list(user.permissions),
        },
        "mcp": mcp,
        "tool": tool,
        "args": args,
        "request_uuid": request_uuid,
    }


async def check(
    client: OPAClient,
    user: UserClaims,
    mcp: str,
    tool: str,
    args: dict[str, Any],
    request_uuid: str,
) -> Decision:
    """Query OPA and increment denial metric on deny."""
    decision = await client.decide(build_input(user, mcp, tool, args, request_uuid))
    if not decision.allow:
        reason_label = (
            decision.reason.split(":", 1)[0]
            if ":" in decision.reason
            else decision.reason
        )
        OPA_DENIALS_TOTAL.labels(mcp=mcp, tool=tool, reason=reason_label).inc()
    return decision
