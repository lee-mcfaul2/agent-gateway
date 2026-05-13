# Writing OPA policies

The gateway's authorization rules live in `policy/authz.rego` + `policy/data/permissions.json`.

The gateway runs only a **coarse reachability check**: "can this user reach this
MCP at all?" Per-tool authorization (row-level filters, field redaction,
tool-specific permissions) is enforced by each MCP under the hybrid authz model.
Each MCP validates the forwarded user JWT and checks its own per-tool
permission table in code.

## Default-deny

The policy is default-deny. If no rule matches, the call is rejected with `reason: "default_deny"`. Adding a new MCP means adding both:
1. An entry under `permissions.<mcp>` in `data/permissions.json` mapping the MCP name to its minimum required permission.
2. The MCP's catalog entry in `lib-agent-prompt`'s OCI bundle.

## Permission scheme

The permissions are strings of the form `<resource>:<verb>`. Examples: `kb:read`, `audit:read`, `crm:read`.

A user's JWT carries `permissions: [...]`. The gateway allows a call to MCP `<mcp>` when the user's permission set contains `data.permissions[<mcp>]`. Anything finer-grained (per-tool perms, per-field redaction) is decided inside the MCP itself.

## Example: adding a new MCP

`crm` MCP is added. Set the minimum reachability permission to `crm:read` (any user with `crm:read` can talk to the MCP; the MCP then decides what each tool needs). Add to `data/permissions.json`:

```json
{
  "permissions": {
    "crm": "crm:read"
  }
}
```

That's it. The Rego policy uses the data table; no code change needed.

## Testing

```bash
opa test policy/ -v
```

Add a corresponding `test_*` rule in `policy/authz_test.rego` for each new MCP.

## Deploying changes

For the demo, `policy/` is mounted as a ConfigMap. Edit + `helm upgrade` to apply.

For production, build a signed OCI bundle and push:

```bash
uv run compile-policy --src policy --out policy.tar.gz --ref ghcr.io/x/agent-gateway-policy:v1 --cosign-key cosign.key
```

Configure the OPA sidecar to pull and verify the signed bundle on a refresh interval.
