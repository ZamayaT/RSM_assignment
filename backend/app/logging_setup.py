"""Logging shared by the backend and the worker.

Every line carries the id of the request being handled (`-` outside a request), so the `requestId` a user sees
in an error can be searched in the log: `docker compose logs backend | grep req-...`.
"""
import contextvars
import logging
import sys

from app.config import get_settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"


class RequestIdFilter(logging.Filter):
    """Adds the current request id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def setup_logging() -> None:
    """Configure the root logger once (safe to call again). The level comes from LOG_LEVEL."""
    root = logging.getLogger()
    handler = next((h for h in root.handlers if getattr(h, "_app_handler", False)), None)
    if handler is None:
        handler = logging.StreamHandler(sys.stderr)
        handler._app_handler = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter(FORMAT))
        handler.addFilter(RequestIdFilter())
        root.addHandler(handler)
    level = logging.getLevelName(get_settings().log_level.upper())
    root.setLevel(level if isinstance(level, int) else logging.INFO)
    # The application writes one access line per request itself (with the request id and the user).
    logging.getLogger("uvicorn.access").disabled = True
