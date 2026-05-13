from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_PROVIDER: TracerProvider | None = None


def setup_tracing(endpoint: str | None, service_name: str) -> None:
    """Configure global tracer provider. If endpoint is None, no-op (still installs provider)."""
    global _PROVIDER
    if _PROVIDER is not None:
        return
    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    if endpoint:
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _PROVIDER = provider


def shutdown_tracing() -> None:
    """Flush + shut down the tracer provider."""
    global _PROVIDER
    if _PROVIDER is not None:
        _PROVIDER.shutdown()
        _PROVIDER = None


def tracer(name: str = "ag_gateway") -> trace.Tracer:
    return trace.get_tracer(name)


@contextmanager
def span(name: str, **attrs: object) -> Iterator[trace.Span]:
    """Start a span with attributes; auto-records exceptions and sets status."""
    with tracer().start_as_current_span(name) as s:
        for k, v in attrs.items():
            s.set_attribute(k, v)  # type: ignore[arg-type]
        yield s
