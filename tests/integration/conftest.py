from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

COMPOSE_FILE = Path(__file__).parent / "compose.yaml"


@pytest.fixture(scope="session")
def integration_stack() -> Iterator[dict[str, str]]:
    """Boot the docker-compose stack once per test session."""
    if not os.environ.get("CI_INTEGRATION_NO_COMPOSE"):
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait"],
            check=True,
        )
    urls = {
        "opa": "http://127.0.0.1:18181",
        "tokenizer": "http://127.0.0.1:18443",
        "postgres": "postgresql://ag:ag@127.0.0.1:5432/ag",
    }
    for _ in range(30):
        try:
            r = httpx.get(urls["tokenizer"] + "/healthz", timeout=1.0)
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    yield urls
    if not os.environ.get("CI_INTEGRATION_NO_COMPOSE"):
        subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
            check=False,
        )
