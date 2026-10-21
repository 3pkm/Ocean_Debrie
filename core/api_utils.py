"""Small HTTP helpers shared by Python Vercel API handlers."""

from __future__ import annotations

import hmac
import json
import math
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Iterable
from urllib.parse import parse_qs, urlsplit

from core.db import get_db_cursor


MAX_REQUEST_BYTES = 1_048_576


class ApiRequestError(ValueError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def parse_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ApiRequestError(f"{field} must be a positive integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.strip().isdigit():
        parsed = int(value.strip())
    else:
        raise ApiRequestError(f"{field} must be a positive integer.")
    if parsed < 1:
        raise ApiRequestError(f"{field} must be a positive integer.")
    return parsed


def validate_timestamp(value: Any, field: str) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiRequestError(f"{field} must be an ISO-8601 timestamp.")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiRequestError(f"{field} must be an ISO-8601 timestamp.") from exc
    return value


def parse_fraction(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ApiRequestError(f"{field} must be between 0 and 1.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ApiRequestError(f"{field} must be numeric.") from exc
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise ApiRequestError(f"{field} must be between 0 and 1.")
    return parsed


def parse_optional_int(value: Any, field: str) -> Any:
    if value is None or value == "":
        return None
    return parse_positive_int(value, field)


def parse_query(handler: Any) -> Dict[str, str]:
    return {
        key: values[-1]
        for key, values in parse_qs(urlsplit(handler.path).query).items()
        if values
    }


def route_parameter(handler: Any, prefix: str) -> str:
    path = urlsplit(handler.path).path.rstrip("/")
    if not path.startswith(prefix):
        return ""
    return path[len(prefix):].strip("/")


def db_fetch_all(sql: str, params: Any = ()) -> list:
    with get_db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def db_fetch_one(sql: str, params: Any = ()) -> Any:
    with get_db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def geojson_value(value: Any) -> Any:
    if value is None or isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if isinstance(value, str):
        return json.loads(value)
    raise ValueError("Database returned an unsupported GeoJSON value.")


def send_unexpected_error(handler: Any, logger: Any, message: str) -> None:
    logger.exception("%s", message)
    send_json(handler, 503, {"error": "Database query failed."})


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def send_json(handler: Any, status_code: int, payload: Any) -> None:
    body = json.dumps(payload, default=_json_default).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: Any) -> Dict[str, Any]:
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except (TypeError, ValueError) as exc:
        raise ApiRequestError("Content-Length must be a valid integer.") from exc
    if content_length < 0 or content_length > MAX_REQUEST_BYTES:
        raise ApiRequestError("Request body is too large.", 413)
    if content_length == 0:
        raise ApiRequestError("A JSON request body is required.")
    try:
        body = json.loads(handler.rfile.read(content_length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiRequestError("Request body must be valid JSON.") from exc
    if not isinstance(body, dict):
        raise ApiRequestError("Request body must be a JSON object.")
    return body


def is_authorized(headers: Any, *configured_secrets: str) -> bool:
    authorization = headers.get("Authorization", "")
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization[7:].strip()
    if not token:
        token = headers.get("X-Ingest-Secret", "").strip()
    if not token:
        return False
    return any(
        secret and hmac.compare_digest(token, secret)
        for secret in configured_secrets
    )


def method_not_allowed(handler: Any, allowed: Iterable[str]) -> None:
    methods = ", ".join(allowed)
    send_json(handler, 405, {"error": "Method not allowed.", "allowed": methods})
