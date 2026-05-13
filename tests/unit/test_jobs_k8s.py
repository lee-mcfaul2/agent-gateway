from __future__ import annotations

from ag_gateway.jobs.k8s import JobSpec, build_job


def test_build_job_basics() -> None:
    spec = JobSpec(
        name="agent-abc",
        namespace="sandbox",
        image="ghcr.io/x/sandbox:v1",
        env={"REQUEST_UUID": "r1", "PROMPT_UUID": "p1"},
    )
    job = build_job(spec)
    assert job.metadata.name == "agent-abc"
    assert job.metadata.namespace == "sandbox"
    assert job.spec.template.spec.runtime_class_name == "gvisor"
    container = job.spec.template.spec.containers[0]
    assert container.image == "ghcr.io/x/sandbox:v1"
    env_map = {e.name: e.value for e in container.env}
    assert env_map["REQUEST_UUID"] == "r1"
    assert env_map["PROMPT_UUID"] == "p1"
    assert job.spec.template.metadata.annotations["linkerd.io/inject"] == "enabled"


def test_pod_label_carries_uuid() -> None:
    spec = JobSpec(
        name="agent-xyz",
        namespace="sandbox",
        image="img",
        env={"REQUEST_UUID": "abc"},
    )
    job = build_job(spec)
    labels = job.spec.template.metadata.labels
    assert labels["request-uuid"] == "abc"


def test_timeout_propagates() -> None:
    spec = JobSpec(name="x", namespace="sandbox", image="img", env={}, timeout_seconds=120)
    job = build_job(spec)
    assert job.spec.active_deadline_seconds == 120
