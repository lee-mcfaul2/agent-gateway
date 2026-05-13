from __future__ import annotations

from dataclasses import dataclass

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config


@dataclass(frozen=True)
class JobSpec:
    name: str
    namespace: str
    image: str
    env: dict[str, str]
    timeout_seconds: int = 300
    service_account: str = "agent-sandbox-sa"
    runtime_class: str = "gvisor"


def load_kube_config() -> None:
    """Try in-cluster first, fall back to kubeconfig."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()


def build_job(spec: JobSpec) -> k8s_client.V1Job:
    """Construct a one-shot K8s Job manifest for the agent."""
    container = k8s_client.V1Container(
        name="agent",
        image=spec.image,
        image_pull_policy="IfNotPresent",
        env=[k8s_client.V1EnvVar(name=k, value=v) for k, v in spec.env.items()],
        resources=k8s_client.V1ResourceRequirements(
            requests={"cpu": "200m", "memory": "256Mi"},
            limits={"cpu": "2", "memory": "1Gi"},
        ),
    )

    pod_spec = k8s_client.V1PodSpec(
        containers=[container],
        restart_policy="Never",
        service_account_name=spec.service_account,
        runtime_class_name=spec.runtime_class,
        automount_service_account_token=True,
    )

    template = k8s_client.V1PodTemplateSpec(
        metadata=k8s_client.V1ObjectMeta(
            labels={"app": "agent-sandbox", "request-uuid": spec.env.get("REQUEST_UUID", "")},
            annotations={"linkerd.io/inject": "enabled"},
        ),
        spec=pod_spec,
    )

    return k8s_client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=k8s_client.V1ObjectMeta(
            name=spec.name,
            namespace=spec.namespace,
            labels={"app": "agent-sandbox"},
        ),
        spec=k8s_client.V1JobSpec(
            template=template,
            backoff_limit=0,
            ttl_seconds_after_finished=60,
            active_deadline_seconds=spec.timeout_seconds,
        ),
    )
