"""Structured JSON logging with secret redaction."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime

_SENSITIVE = re.compile(
    r"(?i)(password|passwd|secret|token|authorization|cookie|api[_-]?key)(\"?\s*[:=]\s*\"?)([^\s\",;&]+)"
)


def redact(text: str) -> str:
    return _SENSITIVE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
