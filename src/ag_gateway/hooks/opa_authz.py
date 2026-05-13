from __future__ import annotations

from typing import Any

from ag_gateway.hooks.auth_oidc import UserClaims
from ag_gateway.hooks.opa_client import Decision, OPAClient
from ag_gateway.obs.metrics import OPA_DENIALS_TOTAL


def build_input(user: UserClaims, mcp: str, request_uuid: str) -> dict[str, Any]:
    """Construct the OPA input document for the coarse (user, mcp) reachability check.

    Per-tool authorization is the MCP's responsibility under the hybrid authz model;
    the gateway only verifies the user can reach the MCP at all.
    """
    return {
        "user": {
            "sub": user.sub,
            "groups": list(user.groups),
            "permissions": list(user.permissions),
        },
        "mcp": mcp,
        "request_uuid": request_uuid,
    }


async def check(
    client: OPAClient,
    user: UserClaims,
    mcp: str,
    request_uuid: str,
) -> Decision:
    """Query OPA for coarse MCP reachability and increment denial metric on deny."""
    decision = await client.decide(build_input(user, mcp, request_uuid))
    if not decision.allow:
        reason_label = (
            decision.reason.split(":", 1)[0]
            if ":" in decision.reason
            else decision.reason
        )
        OPA_DENIALS_TOTAL.labels(mcp=mcp, reason=reason_label).inc()
    return decision
