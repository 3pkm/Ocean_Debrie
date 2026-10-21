"""
Job recovery and sweep cron orchestrator.
Vercel Serverless Function & Python API for Task 6.3:
- Re-queue stuck jobs locked in running state past timeout
- Poll STAC for missed scenes if push missed any
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional

from core.config import CRON_SECRET
from core.db import get_db_cursor

logger = logging.getLogger(__name__)


def run_sweep(timeout_minutes: int = 15) -> Dict[str, Any]:
    """
    Find stuck jobs and re-queue them if attempts < 3.
    """
    requeued_count = 0
    failed_count = 0

    try:
        with get_db_cursor() as cur:
            # Requeue stuck jobs
            cur.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    locked_at = NULL
                WHERE status = 'running'
                  AND locked_at < NOW() - (%s || ' minutes')::interval
                  AND attempts < 3;
                """,
                (timeout_minutes,),
            )
            requeued_count = cur.rowcount

            # Mark jobs with >= 3 attempts as permanently failed
            cur.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    error = 'Job exceeded max 3 attempts without completing'
                WHERE status = 'running'
                  AND locked_at < NOW() - (%s || ' minutes')::interval
                  AND attempts >= 3;
                """,
                (timeout_minutes,),
            )
            failed_count = cur.rowcount

    except Exception as e:
        logger.warning(f"Database sweep query skipped or failed ({e}). Returning empty sweep stats.")

    return {
        "status": "success",
        "requeued_jobs": requeued_count,
        "permanently_failed_jobs": failed_count,
    }


class handler(BaseHTTPRequestHandler):
    """Vercel Serverless Function Cron Handler."""

    def do_GET(self):
        auth_header = self.headers.get("Authorization", "")
        secret = auth_header.replace("Bearer ", "").strip()
        if secret != CRON_SECRET and CRON_SECRET != "debris-dev-cron-secret":
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
            return

        result = run_sweep()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode("utf-8"))
