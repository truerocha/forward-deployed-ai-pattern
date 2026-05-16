"""
A2A Observability — OpenTelemetry Distributed Tracing for Agent Communication.

Provides end-to-end tracing across the A2A workflow graph:
  - Each A2A HTTP call gets a span with traceparent propagation
  - Agent-level spans capture model invocation metrics
  - Workflow-level spans show the full graph execution timeline
  - Traces are exported to AWS X-Ray via the ADOT sidecar collector

Integration Points:
  - HTTPX instrumentation captures A2A JSON-RPC calls automatically
  - FastAPI instrumentation captures inbound requests on A2A servers
  - Custom spans wrap workflow graph node transitions
  - Bedrock invocation metrics are attached as span attributes

Architecture:
  Agent Container → OTel SDK → OTLP/gRPC → ADOT Sidecar → AWS X-Ray

The ADOT (AWS Distro for OpenTelemetry) collector runs as a sidecar container
in the same ECS task definition, receiving traces on localhost:4317 (gRPC)
or localhost:4318 (HTTP) and forwarding them to X-Ray.

Ref: ADR-034 (A2A Protocol), ADR-013 (Enterprise Autonomy and Observability)
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

# Flag to track initialization state
_TRACING_INITIALIZED = False


def inicializar_tracing(
    nome_servico: str,
    endpoint: str | None = None,
    environment: str | None = None,
) -> bool:
    """Initialize OpenTelemetry distributed tracing for an A2A agent.

    Configures the tracer provider with OTLP exporter pointing to the
    ADOT sidecar collector. Instruments HTTPX (used by A2AAgent for
    outbound calls) and FastAPI (used by A2AServer for inbound requests).

    This function is idempotent — calling it multiple times is safe.

    Args:
        nome_servico: Service name that appears in X-Ray traces
                      (e.g., "fde-a2a-pesquisa", "fde-a2a-orchestrator").
        endpoint: OTLP collector endpoint. Defaults to localhost:4317
                  (ADOT sidecar in same ECS task).
        environment: Deployment environment (dev/staging/prod).

    Returns:
        True if tracing was initialized successfully, False otherwise.
    """
    global _TRACING_INITIALIZED

    if _TRACING_INITIALIZED:
        logger.debug("Tracing already initialized for %s", nome_servico)
        return True

    _endpoint = endpoint or os.environ.get(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4317"
    )
    _environment = environment or os.environ.get("ENVIRONMENT", "dev")

    # Skip initialization if no endpoint configured (local dev without collector)
    if not _endpoint or _endpoint == "disabled":
        logger.info("OTel tracing disabled (endpoint=%s)", _endpoint)
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource

        # Resource attributes identify this service in X-Ray
        resource = Resource.create(attributes={
            "service.name": nome_servico,
            "service.version": "1.0.0",
            "deployment.environment": _environment,
            "cloud.provider": "aws",
            "cloud.platform": "aws_ecs",
            "faas.name": nome_servico,
        })

        # Configure tracer provider
        provider = TracerProvider(resource=resource)

        # OTLP exporter → ADOT sidecar (gRPC on localhost:4317)
        exporter = OTLPSpanExporter(
            endpoint=_endpoint,
            insecure=True,  # Localhost communication, no TLS needed
        )

        # Batch processor for efficient span export
        processor = BatchSpanProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=512,
            schedule_delay_millis=5000,
        )
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        # Instrument HTTPX (A2AAgent uses httpx for outbound A2A calls)
        _instrument_httpx()

        # Instrument FastAPI (A2AServer uses FastAPI for inbound requests)
        _instrument_fastapi()

        _TRACING_INITIALIZED = True
        logger.info(
            "OTel tracing initialized: service=%s endpoint=%s env=%s",
            nome_servico, _endpoint, _environment,
        )
        return True

    except ImportError as e:
        logger.warning(
            "OTel dependencies not available (tracing disabled): %s. "
            "Install with: pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-exporter-otlp opentelemetry-instrumentation-httpx "
            "opentelemetry-instrumentation-fastapi",
            str(e),
        )
        return False
    except Exception as e:
        logger.warning("OTel initialization failed (non-blocking): %s", str(e)[:200])
        return False


def _instrument_httpx():
    """Instrument HTTPX client for automatic trace propagation on A2A calls."""
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
        logger.debug("HTTPX instrumentation active")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-httpx not available")
    except Exception as e:
        logger.debug("HTTPX instrumentation failed: %s", str(e)[:100])


def _instrument_fastapi():
    """Instrument FastAPI for automatic span creation on inbound A2A requests."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor().instrument()
        logger.debug("FastAPI instrumentation active")
    except ImportError:
        logger.debug("opentelemetry-instrumentation-fastapi not available")
    except Exception as e:
        logger.debug("FastAPI instrumentation failed: %s", str(e)[:100])


def get_tracer(name: str = "fde.a2a"):
    """Get a tracer instance for creating custom spans.

    Args:
        name: Tracer name (appears in span metadata).

    Returns:
        OpenTelemetry Tracer instance, or a no-op tracer if not initialized.
    """
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


@contextmanager
def trace_workflow_node(
    workflow_id: str,
    node_name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Context manager for tracing a workflow graph node execution.

    Creates a span that wraps the entire node execution, including
    the A2A invocation and any post-processing.

    Usage:
        with trace_workflow_node("wf-123", "PESQUISA", {"query": "..."}):
            result = await agent.invoke(...)

    Args:
        workflow_id: Workflow execution ID (becomes trace attribute).
        node_name: Graph node name (becomes span name).
        attributes: Additional span attributes.
    """
    tracer = get_tracer("fde.a2a.workflow")

    span_attributes = {
        "workflow.id": workflow_id,
        "workflow.node": node_name,
        "workflow.component": "a2a-graph",
    }
    if attributes:
        span_attributes.update(attributes)

    try:
        from opentelemetry import trace

        with tracer.start_as_current_span(
            name=f"a2a.node.{node_name.lower()}",
            attributes=span_attributes,
            kind=trace.SpanKind.INTERNAL,
        ) as span:
            try:
                yield span
            except Exception as e:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)[:200]))
                span.record_exception(e)
                raise

    except ImportError:
        # OTel not available — yield None (no-op)
        yield None


@contextmanager
def trace_a2a_invocation(
    agent_name: str,
    task: str,
    endpoint: str,
) -> Generator[Any, None, None]:
    """Context manager for tracing a single A2A agent invocation.

    Creates a CLIENT span representing the outbound A2A call.
    The HTTPX instrumentation will create a child span for the
    actual HTTP request, linking them automatically.

    Args:
        agent_name: Target agent name (pesquisa/escrita/revisao).
        task: Task description sent to the agent.
        endpoint: A2A server endpoint URL.
    """
    tracer = get_tracer("fde.a2a.client")

    span_attributes = {
        "a2a.agent.name": agent_name,
        "a2a.task": task[:100],
        "a2a.endpoint": endpoint,
        "rpc.system": "a2a",
        "rpc.method": "invoke",
    }

    try:
        from opentelemetry import trace

        with tracer.start_as_current_span(
            name=f"a2a.invoke.{agent_name}",
            attributes=span_attributes,
            kind=trace.SpanKind.CLIENT,
        ) as span:
            try:
                yield span
            except Exception as e:
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)[:200]))
                span.record_exception(e)
                raise

    except ImportError:
        yield None


class _NoOpTracer:
    """No-op tracer for when OpenTelemetry is not installed."""

    def start_as_current_span(self, *args, **kwargs):
        return _NoOpContextManager()

    def start_span(self, *args, **kwargs):
        return _NoOpSpan()


class _NoOpContextManager:
    """No-op context manager for disabled tracing."""

    def __enter__(self):
        return _NoOpSpan()

    def __exit__(self, *args):
        pass


class _NoOpSpan:
    """No-op span for disabled tracing."""

    def set_attribute(self, key, value):
        pass

    def set_status(self, status):
        pass

    def record_exception(self, exception):
        pass

    def add_event(self, name, attributes=None):
        pass
