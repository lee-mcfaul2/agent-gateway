package ag_gateway.authz

# default decision: deny
default decision := {"allow": false, "reason": "default_deny"}

# allow when every required permission is in the user's permission set
decision := {"allow": true, "reason": "ok"} if {
    required := data.permissions[input.mcp][input.tool]
    every p in required {
        p in input.user.permissions
    }
}

# explicit reason for the common "missing permission" case
decision := {"allow": false, "reason": reason} if {
    required := data.permissions[input.mcp][input.tool]
    missing := [p | p := required[_]; not p in input.user.permissions]
    count(missing) > 0
    reason := sprintf("missing_permission:%s", [missing[0]])
}

# explicit reason when the MCP/tool isn't registered (treat as deny — never silently allow)
decision := {"allow": false, "reason": "unknown_tool"} if {
    not data.permissions[input.mcp]
}
decision := {"allow": false, "reason": "unknown_tool"} if {
    data.permissions[input.mcp]
    not data.permissions[input.mcp][input.tool]
}
