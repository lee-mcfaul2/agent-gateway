from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ag_gateway.mcp_proxy.routes import Deps, make_router
from ag_gateway.prompts.bundle_view import BundleView

FIXTURE_BUNDLE = Path(__file__).parent.parent / "fixtures" / "bundle-v1"


def _deps(view: BundleView) -> Deps:
    return Deps(
        state=MagicMock(),
        mcps=MagicMock(),
        mcp_pool=MagicMock(),
        schemas=MagicMock(),
        tokenizer=MagicMock(),
        opa=MagicMock(),
        scrub_engine=MagicMock(),
        bundle=view,
        llm_guard=MagicMock(),
    )


def test_bundle_digest_endpoint():
    view = BundleView.from_bundle(FIXTURE_BUNDLE)
    app = FastAPI()
    app.include_router(make_router(_deps(view)))
    client = TestClient(app)

    r = client.get("/v1/bundle_digest")
    assert r.status_code == 200
    body = r.json()
    assert body["digest"] == view.digest
    assert body["digest"].startswith("sha256:")
