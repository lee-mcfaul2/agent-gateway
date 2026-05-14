from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ag_gateway.jobs.launcher import (
    AgentFailedError,
    AgentJobLauncher,
    JobResult,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FULL_KWARGS: dict[str, Any] = dict(
    request_uuid="11111111-1111-1111-1111-111111111111",
    prompt_uuid="22222222-2222-2222-2222-222222222222",
    litellm_url="http://gateway:4000",
    gateway_mcp_url="http://gateway:8080",
    tokenized_user_input="hello",
    available_tools=["kb.search", "audit_db.search"],
    model="claude-sonnet-4-6",
    max_iterations=8,
    wallclock_timeout_seconds=120,
    traceparent="00-aaa-bbb-01",
)

# Minimal kwargs for tests that don't care about the full set
_MINIMAL_KWARGS: dict[str, Any] = dict(
    request_uuid="r1",
    prompt_uuid="p1",
    litellm_url="http://litellm",
    gateway_mcp_url="http://gw:8080",
    tokenized_user_input="hello",
    available_tools=["tool.a"],
    model="claude-sonnet-4-6",
    max_iterations=5,
    wallclock_timeout_seconds=60,
    traceparent="00-xxx-yyy-01",
)


class _FakeBatch:
    def __init__(self, succeed_after: int = 1, fail: bool = False) -> None:
        self.calls = 0
        self.succeed_after = succeed_after
        self.fail = fail
        self.created: list[Any] = []

    def create_namespaced_job(self, ns: str, body: Any) -> None:
        self.created.append((ns, body))

    def read_namespaced_job_status(self, name: str, ns: str) -> Any:
        self.calls += 1
        if self.fail:
            return SimpleNamespace(status=SimpleNamespace(succeeded=0, failed=1))
        if self.calls >= self.succeed_after:
            return SimpleNamespace(status=SimpleNamespace(succeeded=1, failed=0))
        return SimpleNamespace(status=SimpleNamespace(succeeded=0, failed=0))

    def delete_namespaced_job(self, name: str, ns: str, **kw: Any) -> None:
        pass


class _FakeCore:
    def __init__(self, logs: str) -> None:
        self._logs = logs

    def list_namespaced_pod(self, ns: str, label_selector: str) -> Any:
        return SimpleNamespace(
            items=[SimpleNamespace(metadata=SimpleNamespace(name="pod-1"))]
        )

    def read_namespaced_pod_log(self, name: str, ns: str, **kw: Any) -> str:
        return self._logs


# ---------------------------------------------------------------------------
# Happy-path test
# ---------------------------------------------------------------------------


async def test_launch_and_wait_ok() -> None:
    batch = _FakeBatch(succeed_after=1)
    core = _FakeCore('{"terminate": {"answer": "hi"}}\n')
    launcher = AgentJobLauncher(
        batch_api=batch,  # type: ignore[arg-type]
        core_api=core,  # type: ignore[arg-type]
        namespace="sandbox",
        image="img",
        poll_interval_seconds=0.001,
    )
    res = await launcher.launch_and_wait(**_MINIMAL_KWARGS)
    assert isinstance(res, JobResult)
    assert res.terminate_body == {"answer": "hi"}


# ---------------------------------------------------------------------------
# Error-path tests
# ---------------------------------------------------------------------------


async def test_failed_job_raises() -> None:
    batch = _FakeBatch(fail=True)
    core = _FakeCore("")
    launcher = AgentJobLauncher(
        batch_api=batch,  # type: ignore[arg-type]
        core_api=core,  # type: ignore[arg-type]
        namespace="sandbox",
        image="img",
        poll_interval_seconds=0.001,
    )
    with pytest.raises(AgentFailedError):
        await launcher.launch_and_wait(**_MINIMAL_KWARGS)


async def test_no_terminate_in_logs_raises() -> None:
    batch = _FakeBatch(succeed_after=1)
    core = _FakeCore("just some stdout text\n")
    launcher = AgentJobLauncher(
        batch_api=batch,  # type: ignore[arg-type]
        core_api=core,  # type: ignore[arg-type]
        namespace="sandbox",
        image="img",
        poll_interval_seconds=0.001,
    )
    with pytest.raises(AgentFailedError):
        await launcher.launch_and_wait(**_MINIMAL_KWARGS)


# ---------------------------------------------------------------------------
# New: all 10 env vars are set correctly
# ---------------------------------------------------------------------------


def test_launcher_passes_full_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify all 10 env vars are populated on the Job spec."""
    import asyncio
    from unittest.mock import MagicMock

    batch_api = MagicMock()
    core_api = MagicMock()

    captured: dict[str, Any] = {}

    def fake_create(namespace: str, job: Any) -> MagicMock:
        captured["job"] = job
        return MagicMock()

    batch_api.create_namespaced_job = fake_create

    launcher = AgentJobLauncher(
        batch_api,
        core_api,
        namespace="sandbox",
        image="agent-sandbox:test",
        timeout_seconds=600,
    )

    async def fake_wait(name: str) -> JobResult:
        return JobResult(
            name=name,
            terminate_body={
                "terminate": {
                    "request_uuid": "u",
                    "prompt_uuid": "p",
                    "response": "x",
                    "iterations": 0,
                    "tools_called": [],
                    "model": "m",
                    "finish_reason": "terminate",
                }
            },
        )

    launcher._wait = fake_wait  # type: ignore[method-assign]

    asyncio.get_event_loop().run_until_complete(
        launcher.launch_and_wait(**_FULL_KWARGS)
    )

    job_spec = captured["job"]
    containers = job_spec.spec.template.spec.containers
    env = {e.name: e.value for c in containers for e in (c.env or [])}

    assert env["REQUEST_UUID"] == "11111111-1111-1111-1111-111111111111"
    assert env["PROMPT_UUID"] == "22222222-2222-2222-2222-222222222222"
    assert env["LITELLM_URL"] == "http://gateway:4000"
    assert env["GATEWAY_MCP_URL"] == "http://gateway:8080"
    assert env["AVAILABLE_TOOLS"] == "kb.search,audit_db.search"
    assert env["TOKENIZED_USER_INPUT"] == "hello"
    assert env["MODEL"] == "claude-sonnet-4-6"
    assert env["MAX_ITERATIONS"] == "8"
    assert env["WALLCLOCK_TIMEOUT_SECONDS"] == "120"
    assert env["TRACEPARENT"] == "00-aaa-bbb-01"


# ---------------------------------------------------------------------------
# New: wallclock_timeout_seconds controls activeDeadlineSeconds (+30s buffer)
# ---------------------------------------------------------------------------


def test_wallclock_timeout_sets_active_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """activeDeadlineSeconds == wallclock_timeout_seconds + 30."""
    import asyncio
    from unittest.mock import MagicMock

    batch_api = MagicMock()
    core_api = MagicMock()

    captured: dict[str, Any] = {}

    def fake_create(namespace: str, job: Any) -> MagicMock:
        captured["job"] = job
        return MagicMock()

    batch_api.create_namespaced_job = fake_create

    launcher = AgentJobLauncher(
        batch_api,
        core_api,
        namespace="sandbox",
        image="agent-sandbox:test",
        timeout_seconds=600,
    )

    async def fake_wait(name: str) -> JobResult:
        return JobResult(
            name=name,
            terminate_body={},
        )

    launcher._wait = fake_wait  # type: ignore[method-assign]

    kwargs = dict(_FULL_KWARGS, wallclock_timeout_seconds=90)
    asyncio.get_event_loop().run_until_complete(launcher.launch_and_wait(**kwargs))

    job_spec = captured["job"]
    assert job_spec.spec.active_deadline_seconds == 90 + 30


# ---------------------------------------------------------------------------
# New: available_tools list is joined with ','
# ---------------------------------------------------------------------------


def test_available_tools_joined(monkeypatch: pytest.MonkeyPatch) -> None:
    """AVAILABLE_TOOLS env var is a comma-joined string of the list."""
    import asyncio
    from unittest.mock import MagicMock

    batch_api = MagicMock()
    core_api = MagicMock()

    captured: dict[str, Any] = {}

    def fake_create(namespace: str, job: Any) -> MagicMock:
        captured["job"] = job
        return MagicMock()

    batch_api.create_namespaced_job = fake_create

    launcher = AgentJobLauncher(
        batch_api,
        core_api,
        namespace="sandbox",
        image="agent-sandbox:test",
        timeout_seconds=600,
    )

    async def fake_wait(name: str) -> JobResult:
        return JobResult(name=name, terminate_body={})

    launcher._wait = fake_wait  # type: ignore[method-assign]

    kwargs = dict(_FULL_KWARGS, available_tools=["alpha", "beta", "gamma"])
    asyncio.get_event_loop().run_until_complete(launcher.launch_and_wait(**kwargs))

    containers = captured["job"].spec.template.spec.containers
    env = {e.name: e.value for c in containers for e in (c.env or [])}
    assert env["AVAILABLE_TOOLS"] == "alpha,beta,gamma"
