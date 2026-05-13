package ag_gateway.authz_test

import data.ag_gateway.authz

test_allow_when_permission_present if {
    authz.decision == {"allow": true, "reason": "ok"} with input as {
        "user": {"sub": "alice", "permissions": ["kb:read"]},
        "mcp": "kb",
        "tool": "search",
    } with data.permissions as {"kb": {"search": ["kb:read"]}}
}

test_deny_missing_permission if {
    d := authz.decision with input as {
        "user": {"sub": "alice", "permissions": []},
        "mcp": "audit_db",
        "tool": "search",
    } with data.permissions as {"audit_db": {"search": ["audit:read"]}}
    d.allow == false
    startswith(d.reason, "missing_permission")
}

test_deny_unknown_mcp if {
    d := authz.decision with input as {
        "user": {"sub": "alice", "permissions": []},
        "mcp": "nope",
        "tool": "x",
    } with data.permissions as {"kb": {"search": ["kb:read"]}}
    d.allow == false
    d.reason == "unknown_tool"
}

test_deny_unknown_tool if {
    d := authz.decision with input as {
        "user": {"sub": "alice", "permissions": ["kb:read"]},
        "mcp": "kb",
        "tool": "delete",
    } with data.permissions as {"kb": {"search": ["kb:read"]}}
    d.allow == false
    d.reason == "unknown_tool"
}
