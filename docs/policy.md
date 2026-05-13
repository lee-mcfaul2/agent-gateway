# Writing OPA policies

The gateway's authorization rules live in `policy/authz.rego` + `policy/data/permissions.json`.

## Default-deny

The policy is default-deny. If no rule matches, the call is rejected with `reason: "default_deny"`. Adding a new MCP means adding both:
1. An entry under `permissions.<mcp>` in `data/permissions.json`
2. The MCP's catalog entry in `lib-agent-prompt`'s OCI bundle

## Permission scheme

The permissions are strings of the form `<resource>:<verb>`. Examples: `kb:read`, `audit:read`, `audit:export`, `crm:write`.

A user's JWT carries `permissions: [...]`. A tool call is allowed when **every** permission required by `(mcp, tool)` is in the user's list.

## Example: adding a new tool

`crm` MCP gains a new `update_contact` tool that needs `crm:write`. Add to `data/permissions.json`:

```json
{
  "permissions": {
    "crm": {
      "search": ["crm:read"],
      "update_contact": ["crm:write"]
    }
  }
}
```

That's it. The Rego policy uses the data table; no code change needed.

## Testing

```bash
opa test policy/ -v
```

Add a corresponding `test_*` rule in `policy/authz_test.rego` for each new permission scheme.

## Deploying changes

For the demo, `policy/` is mounted as a ConfigMap. Edit + `helm upgrade` to apply.

For production, build a signed OCI bundle and push:

```bash
uv run compile-policy --src policy --out policy.tar.gz --ref ghcr.io/x/agent-gateway-policy:v1 --cosign-key cosign.key
```

Configure the OPA sidecar to pull and verify the signed bundle on a refresh interval.
