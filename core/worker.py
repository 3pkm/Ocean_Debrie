"""Internal invocation of the existing process-scene queue handler."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.config import CRON_SECRET, INGEST_SECRET, WORKER_URL

logger = logging.getLogger(__name__)


def trigger_process_scene(timeout_seconds: float = 5.0) -> Dict[str, Any]:
    """Ask the configured process-scene endpoint to claim one queued job."""
    if not WORKER_URL:
        return {"status": "failed", "reason": "worker_url_not_configured"}
    secret = CRON_SECRET or INGEST_SECRET
    if not secret:
        return {"status": "failed", "reason": "worker_secret_not_configured"}

    request = Request(
        WORKER_URL,
        data=json.dumps({}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status < 200 or response.status >= 300:
                return {
                    "status": "failed",
                    "http_status": response.status,
                    "reason": "worker_rejected_request",
                }
            return {"status": "triggered", "http_status": response.status}
    except HTTPError as exc:
        logger.warning("Worker invocation returned HTTP %s.", exc.code)
        return {
            "status": "failed",
            "http_status": exc.code,
            "reason": "worker_rejected_request",
        }
    except (URLError, TimeoutError, OSError) as exc:
        logger.exception("Worker invocation failed.")
        return {"status": "failed", "reason": type(exc).__name__}
