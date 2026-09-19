import json
import logging

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

logger = logging.getLogger("flowpilot")


def build_tracer(endpoint: str | None = None):
    provider = TracerProvider(resource=Resource.create({"service.name": "flowpilot", "service.version": "0.1.0"}))
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    return provider, provider.get_tracer("flowpilot")


def log_event(event: str, **fields):
    logger.info(json.dumps({"event": event, **fields}, separators=(",", ":")))
