"""BundleView — immutable view over a v1.0 lib-agent-prompt bundle.

Replaces the old PromptRegistry. Exposes:
  - digest (sha256:... computed across the schema set)
  - user_prompt / final_response / tool_result validators
  - services dict (mcp_name -> [ToolEntry])
  - envelope_cost_caps (default ceiling on max_iterations / max_wallclock / max_cost)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ag_gateway.obs.logging import get_logger
from ag_gateway.schemas.validate import SchemaValidator, compile_schema

log = get_logger(__name__)


@dataclass(frozen=True)
class CostCaps:
    max_iterations: int
    max_wallclock_ms: int
    max_cost_usd: float


@dataclass(frozen=True)
class ToolEntry:
    name: str
    write: bool
    requires_permissions: list[str] = field(default_factory=list)
    request_validator: SchemaValidator | None = None


@dataclass(frozen=True)
class BundleView:
    digest: str
    user_prompt_validator: SchemaValidator
    final_response_validator: SchemaValidator
    tool_result_validator: SchemaValidator
    services: dict[str, list[ToolEntry]]
    envelope_cost_caps: CostCaps

    @classmethod
    def from_bundle(cls, root: Path) -> BundleView:
        root = Path(root)
        if not root.exists():
            raise FileNotFoundError(f"bundle root not found: {root}")

        # Load envelope schema bytes (for digest) and compile validators.
        user_prompt_bytes = (root / "schemas" / "user-prompt.json").read_bytes()
        final_response_bytes = (root / "schemas" / "final-response.json").read_bytes()
        tool_result_bytes = (root / "schemas" / "tool-result.json").read_bytes()

        # Shared schemas (e.g. uuid.json) for $ref resolution.
        shared_dir = root / "schemas" / "shared"
        shared_resources: dict[str, dict] = {}
        if shared_dir.exists():
            for p in sorted(shared_dir.glob("*.json")):
                shared_resources[f"shared/{p.name}"] = json.loads(p.read_text())

        user_prompt_validator = compile_schema(
            json.loads(user_prompt_bytes), shared_resources
        )
        final_response_validator = compile_schema(
            json.loads(final_response_bytes), shared_resources
        )
        tool_result_validator = compile_schema(
            json.loads(tool_result_bytes), shared_resources
        )

        # Manifest gives us envelope_cost_caps.
        manifest = json.loads((root / "bundle-manifest.json").read_text())
        caps = CostCaps(
            max_iterations=int(manifest["envelope_cost_caps"]["max_iterations"]),
            max_wallclock_ms=int(manifest["envelope_cost_caps"]["max_wallclock_ms"]),
            max_cost_usd=float(manifest["envelope_cost_caps"]["max_cost_usd"]),
        )

        # Per-tool schemas live at schemas/services/<mcp>/<tool>.{request,response,meta}.json
        services: dict[str, list[ToolEntry]] = {}
        services_root = root / "schemas" / "services"
        bytes_for_digest: list[bytes] = [
            user_prompt_bytes,
            final_response_bytes,
            tool_result_bytes,
        ]
        for mcp_dir in sorted(services_root.iterdir()):
            if not mcp_dir.is_dir():
                continue
            # Group files by tool base name, then by kind suffix.
            tools_by_name: dict[str, dict[str, Path]] = {}
            for p in sorted(mcp_dir.glob("*.json")):
                # e.g. "search.request.json" -> base="search", kind="request"
                # stem is "search.request"; rpartition on "." gives ("search", ".", "request")
                base, _, kind = p.stem.rpartition(".")
                if not base:
                    continue
                tools_by_name.setdefault(base, {})[kind] = p
            tool_list: list[ToolEntry] = []
            for tool_name, files in sorted(tools_by_name.items()):
                req_path = files.get("request")
                resp_path = files.get("response")
                meta_path = files.get("meta")
                if req_path is None or resp_path is None:
                    continue
                meta = json.loads(meta_path.read_text()) if meta_path else {}
                req_validator = compile_schema(
                    json.loads(req_path.read_text()), shared_resources
                )
                tool_list.append(
                    ToolEntry(
                        name=tool_name,
                        write=bool(meta.get("write", False)),
                        requires_permissions=list(meta.get("requires_permissions", [])),
                        request_validator=req_validator,
                    )
                )
                bytes_for_digest.append(req_path.read_bytes())
                bytes_for_digest.append(resp_path.read_bytes())
            services[mcp_dir.name] = tool_list

        # Stable digest across all schema bytes.
        h = hashlib.sha256()
        for b in bytes_for_digest:
            h.update(b)
            h.update(b"\x00")
        digest = "sha256:" + h.hexdigest()

        log.info(
            "bundle_view.loaded",
            digest=digest,
            mcps=list(services.keys()),
            tool_count=sum(len(v) for v in services.values()),
        )

        return cls(
            digest=digest,
            user_prompt_validator=user_prompt_validator,
            final_response_validator=final_response_validator,
            tool_result_validator=tool_result_validator,
            services=services,
            envelope_cost_caps=caps,
        )
