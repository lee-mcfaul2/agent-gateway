from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from ag_gateway.jobs.launcher import (
    AgentFailedError,
    AgentJobLauncher,
    JobResult,
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
    res = await launcher.launch_and_wait("r1", "p1", "http://litellm", "hello")
    assert isinstance(res, JobResult)
    assert res.terminate_body == {"answer": "hi"}


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
        await launcher.launch_and_wait("r1", "p1", "http://x", "x")


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
        await launcher.launch_and_wait("r1", "p1", "http://x", "x")
