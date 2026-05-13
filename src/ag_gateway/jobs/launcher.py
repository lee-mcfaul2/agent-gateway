from __future__ import annotations

import asyncio
import json
import time
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from kubernetes import client as k8s_client

from ag_gateway.jobs.k8s import JobSpec, build_job
from ag_gateway.obs.logging import get_logger


log = get_logger(__name__)


class AgentLaunchError(Exception):
    pass


class AgentTimeoutError(Exception):
    pass


class AgentFailedError(Exception):
    pass


@dataclass(frozen=True)
class JobResult:
    name: str
    terminate_body: dict[str, Any]


class AgentJobLauncher:
    """Launches one-shot Jobs and waits for the terminate output."""

    def __init__(
        self,
        batch_api: k8s_client.BatchV1Api,
        core_api: k8s_client.CoreV1Api,
        namespace: str,
        image: str,
        timeout_seconds: int = 300,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._batch = batch_api
        self._core = core_api
        self._ns = namespace
        self._image = image
        self._timeout = timeout_seconds
        self._poll = poll_interval_seconds

    async def launch_and_wait(
        self,
        request_uuid: str,
        prompt_uuid: str,
        litellm_url: str,
        tokenized_user_input: str,
    ) -> JobResult:
        name = f"agent-{request_uuid[:8]}-{_uuid.uuid4().hex[:6]}"
        spec = JobSpec(
            name=name,
            namespace=self._ns,
            image=self._image,
            env={
                "REQUEST_UUID": request_uuid,
                "PROMPT_UUID": prompt_uuid,
                "LITELLM_URL": litellm_url,
                "TOKENIZED_USER_INPUT": tokenized_user_input,
            },
            timeout_seconds=self._timeout,
        )

        try:
            self._batch.create_namespaced_job(self._ns, build_job(spec))
        except k8s_client.exceptions.ApiException as exc:
            raise AgentLaunchError(f"k8s rejected job: {exc.status} {exc.reason}") from exc

        log.info("agent.launched", name=name, request_uuid=request_uuid)

        try:
            return await self._wait(name)
        finally:
            try:
                self._batch.delete_namespaced_job(
                    name, self._ns, propagation_policy="Background"
                )
            except Exception:
                pass

    async def _wait(self, name: str) -> JobResult:
        deadline = time.time() + self._timeout
        while time.time() < deadline:
            try:
                job = self._batch.read_namespaced_job_status(name, self._ns)
            except k8s_client.exceptions.ApiException as exc:
                raise AgentLaunchError(f"job status read failed: {exc.status}") from exc

            status = job.status
            if status.succeeded:
                return JobResult(name=name, terminate_body=self._read_terminate(name))
            if status.failed:
                raise AgentFailedError(f"job {name} failed")
            await asyncio.sleep(self._poll)
        raise AgentTimeoutError(f"job {name} did not terminate in {self._timeout}s")

    def _read_terminate(self, name: str) -> dict[str, Any]:
        pods = self._core.list_namespaced_pod(
            self._ns, label_selector=f"job-name={name}"
        )
        if not pods.items:
            raise AgentFailedError(f"no pod for job {name}")
        pod_name = pods.items[0].metadata.name
        logs = self._core.read_namespaced_pod_log(pod_name, self._ns, tail_lines=200)

        for line in reversed(logs.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    body = json.loads(line)
                    if isinstance(body, dict) and "terminate" in body:
                        return body["terminate"]
                except json.JSONDecodeError:
                    continue
        raise AgentFailedError(f"could not find terminate body in logs for {name}")
