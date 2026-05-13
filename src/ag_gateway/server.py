from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, Response
from kubernetes import client as k8s_client

from ag_gateway.config import load_settings
from ag_gateway.hooks.audit import AuditLogger
from ag_gateway.hooks.auth_oidc import OIDCValidator
from ag_gateway.hooks.cost_cap import CostMeter
from ag_gateway.hooks.opa_client import OPAClient
from ag_gateway.hooks.scrub_engine import ScrubEngine
from ag_gateway.hooks.tokenizer_client import TokenizerClient
from ag_gateway.jobs.k8s import load_kube_config
from ag_gateway.jobs.launcher import AgentJobLauncher
from ag_gateway.mcp_proxy.client import MCPClientPool
from ag_gateway.mcp_proxy.handshake import handshake_all
from ag_gateway.mcp_proxy.registry import MCPRegistry
from ag_gateway.mcp_proxy.request_state import RequestStateStore
from ag_gateway.mcp_proxy.routes import Deps as MCPDeps
from ag_gateway.mcp_proxy.routes import make_router as make_mcp_router
from ag_gateway.obs.logging import get_logger, setup_logging
from ag_gateway.obs.metrics import render_text
from ag_gateway.obs.quarantine import QuarantineStore
from ag_gateway.obs.tracing import setup_tracing, shutdown_tracing
from ag_gateway.prompts.bundle import pull_and_verify
from ag_gateway.prompts.registry import PromptRegistry
from ag_gateway.schemas.scrub_categories import ScrubCatalog
from ag_gateway.schemas.validate import SchemaRegistry
from ag_gateway.server_ingress import IngressDeps
from ag_gateway.server_ingress import make_router as make_ingress_router


log = get_logger(__name__)


async def build_app() -> tuple[FastAPI, dict[str, object]]:
    settings = load_settings()
    setup_logging(settings.log_level, settings.service_name)
    setup_tracing(settings.otel_exporter_otlp_endpoint, settings.service_name)

    log.info("startup.bundle.pulling", ref=settings.prompt_bundle_ref)
    bundle = await pull_and_verify(
        ref=settings.prompt_bundle_ref,
        cosign_public_key=settings.prompt_bundle_cosign_key,
        dest_root=Path("/var/lib/ag-gateway/bundle"),
    )
    log.info("startup.bundle.verified", digest=bundle.digest)

    prompts = PromptRegistry.from_bundle(bundle.root)
    mcps = MCPRegistry.from_bundle(bundle.root)
    scrub_catalog = ScrubCatalog.from_bundle(bundle.root)
    schemas = SchemaRegistry(bundle.root)

    tokenizer = TokenizerClient(str(settings.tokenizer_url))
    opa = OPAClient(str(settings.opa_url))

    oidc = OIDCValidator(
        issuer=str(settings.oidc_issuer),
        audience=settings.oidc_audience,
        refresh_seconds=settings.jwks_refresh_seconds,
    )

    log.info("startup.mcp.handshaking", count=len(mcps.names()))
    handshakes = await handshake_all(mcps)
    log.info("startup.mcp.complete", results=handshakes)

    audit = AuditLogger(str(settings.audit_database_url))
    await audit.start()
    quarantine = QuarantineStore(
        str(settings.audit_database_url),
        snapshot_max_bytes=settings.quarantine_snapshot_max_bytes,
    )
    await quarantine.start()

    load_kube_config()
    batch = k8s_client.BatchV1Api()
    core = k8s_client.CoreV1Api()
    launcher = AgentJobLauncher(
        batch_api=batch,
        core_api=core,
        namespace=settings.agent_job_namespace,
        image=settings.agent_job_image,
        timeout_seconds=settings.agent_job_timeout_seconds,
    )

    scrub_engine = ScrubEngine(scrub_catalog)
    state = RequestStateStore()
    cost_meter = CostMeter()
    mcp_pool = MCPClientPool()

    app = FastAPI(title="agent-gateway", version="0.1.0")

    ingress_deps = IngressDeps(
        oidc=oidc,
        prompts=prompts,
        scrub_engine=scrub_engine,
        tokenizer=tokenizer,
        state=state,
        launcher=launcher,
        audit=audit,
        quarantine=quarantine,
        cost_meter=cost_meter,
        litellm_internal_url=f"http://localhost:{settings.listen_addr.lstrip(':')}",
    )
    app.include_router(make_ingress_router(ingress_deps))

    mcp_deps = MCPDeps(
        state=state,
        mcps=mcps,
        mcp_pool=mcp_pool,
        schemas=schemas,
        tokenizer=tokenizer,
        opa=opa,
        scrub_engine=scrub_engine,
    )
    app.include_router(make_mcp_router(mcp_deps))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> Response:
        try:
            await tokenizer._client.get("/healthz", timeout=0.5)  # type: ignore[attr-defined]
        except Exception:
            return PlainTextResponse("tokenizer", status_code=503)
        try:
            await opa._client.get("/health", timeout=0.5)  # type: ignore[attr-defined]
        except Exception:
            return PlainTextResponse("opa", status_code=503)
        return PlainTextResponse("ok", status_code=200)

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(content=render_text(), media_type="text/plain; version=0.0.4")

    cleanup_handles: dict[str, object] = {
        "audit": audit,
        "quarantine": quarantine,
        "tokenizer": tokenizer,
        "opa": opa,
        "mcp_pool": mcp_pool,
    }
    return app, cleanup_handles


async def _serve() -> None:
    app, cleanup = await build_app()
    settings = load_settings()
    host, _, port = settings.listen_addr.lstrip(":").partition(":")
    if not port:
        port = host
        host = "0.0.0.0"
    config = uvicorn.Config(app, host=host, port=int(port), log_config=None)
    server = uvicorn.Server(config)

    async def _on_signal() -> None:
        log.info("server.shutdown_requested")
        server.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(_on_signal()))

    try:
        await server.serve()
    finally:
        log.info("server.cleaning_up")
        for name, handle in cleanup.items():
            try:
                stop = getattr(handle, "stop", None) or getattr(handle, "aclose", None)
                if stop is not None:
                    await stop() if asyncio.iscoroutinefunction(stop) else stop()
            except Exception as exc:
                log.warning("server.cleanup_error", name=name, err=str(exc))
        shutdown_tracing()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
