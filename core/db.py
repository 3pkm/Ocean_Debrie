"""
Database helper module for Neon Postgres + PostGIS using psycopg 3.
Provides connection pooling, transaction context managers, and job row-locking.
"""

import contextlib
import logging
import math
from typing import Generator, Any, Optional, Dict
from core.config import DATABASE_URL, DATABASE_URL_UNPOOLED

logger = logging.getLogger(__name__)

# Attempt to import psycopg; fallback to None if dependencies not yet installed
try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
except ImportError:
    psycopg = None
    dict_row = None
    ConnectionPool = None

_pool: Optional[Any] = None


def get_connection_pool(min_size: int = 1, max_size: int = 10) -> Optional[Any]:
    """Retrieve or initialize the global connection pool."""
    global _pool
    if _pool is not None:
        return _pool

    if not DATABASE_URL or ConnectionPool is None:
        logger.warning("DATABASE_URL not configured or psycopg_pool not installed.")
        return None

    try:
        # Neon pooled connection string works well with psycopg ConnectionPool
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        return _pool
    except Exception as e:
        logger.error(f"Failed to initialize database connection pool: {e}")
        return None


@contextlib.contextmanager
def get_db_connection() -> Generator[Any, None, None]:
    """Yield a database connection from the pool or direct connection."""
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Install psycopg[binary] and psycopg_pool.")

    pool = get_connection_pool()
    if pool is not None:
        with pool.connection() as conn:
            yield conn
    else:
        # Fallback to direct single connection if pool unavailable
        conn_str = DATABASE_URL_UNPOOLED or DATABASE_URL
        if not conn_str:
            raise ValueError("Neither DATABASE_URL nor DATABASE_URL_UNPOOLED is set.")
        with psycopg.connect(conn_str, row_factory=dict_row) as conn:
            yield conn


@contextlib.contextmanager
def get_db_cursor() -> Generator[Any, None, None]:
    """Context manager for obtaining a database cursor with automatic commit/rollback."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            yield cur
        conn.commit()


def lock_and_acquire_job(job_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Acquire a queued job using SELECT ... FOR UPDATE SKIP LOCKED.
    Marks status as 'running' and sets locked_at = now().
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if job_id is not None:
                cur.execute(
                    """
                    SELECT j.job_id, j.kind, j.scene_id, j.status, j.attempts,
                           s.aoi_id
                    FROM jobs AS j
                    LEFT JOIN scenes AS s ON s.scene_id = j.scene_id
                    WHERE j.job_id = %s AND j.status = 'queued'
                    FOR UPDATE OF j SKIP LOCKED;
                    """,
                    (job_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT j.job_id, j.kind, j.scene_id, j.status, j.attempts,
                           s.aoi_id
                    FROM jobs AS j
                    LEFT JOIN scenes AS s ON s.scene_id = j.scene_id
                    WHERE j.status = 'queued'
                    ORDER BY j.created_at ASC
                    LIMIT 1
                    FOR UPDATE OF j SKIP LOCKED;
                    """
                )
            job = cur.fetchone()
            if not job:
                return None

            cur.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    locked_at = now(),
                    attempts = attempts + 1
                WHERE job_id = %s
                RETURNING job_id, kind, scene_id, status, attempts;
                """,
                (job["job_id"],),
            )
            updated_job = cur.fetchone()
            updated_job["aoi_id"] = job["aoi_id"]
            conn.commit()
            return updated_job


def finish_job(job_id: int, status: str = "done", error: Optional[str] = None) -> None:
    """Mark a job as done or failed."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = %s,
                error = %s
            WHERE job_id = %s;
            """,
            (status, error, job_id),
        )


def enqueue_scene_job(
    scene_id: str,
    aoi_id: Optional[int] = None,
    sensing_time: Optional[Any] = None,
    source: str = "api",
    cloud_frac: float = 0.0,
) -> Dict[str, Any]:
    """Register a scene and atomically enqueue its existing process-scene job."""
    if not scene_id or not scene_id.strip():
        raise ValueError("scene_id is required.")
    if not math.isfinite(cloud_frac) or not 0.0 <= cloud_frac <= 1.0:
        raise ValueError("cloud_frac must be between 0 and 1.")
    if psycopg is None:
        raise RuntimeError("psycopg is not installed.")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Serialize enqueue attempts for one scene even when callers race.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint);",
                (scene_id,),
            )
            cur.execute(
                """
                INSERT INTO scenes
                    (scene_id, aoi_id, sensing_time, source, cloud_frac, status)
                VALUES (%s, %s, %s, %s, %s, 'queued')
                ON CONFLICT (scene_id) DO UPDATE SET
                    aoi_id = COALESCE(scenes.aoi_id, EXCLUDED.aoi_id),
                    sensing_time = COALESCE(scenes.sensing_time, EXCLUDED.sensing_time),
                    source = COALESCE(scenes.source, EXCLUDED.source),
                    cloud_frac = COALESCE(scenes.cloud_frac, EXCLUDED.cloud_frac);
                """,
                (scene_id, aoi_id, sensing_time, source, cloud_frac),
            )
            cur.execute(
                """
                SELECT job_id, status, attempts
                FROM jobs
                WHERE scene_id = %s AND kind = 'process_scene'
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE;
                """,
                (scene_id,),
            )
            existing = cur.fetchone()
            if existing:
                status = existing["status"]
                if status == "failed":
                    if (existing["attempts"] or 0) >= 3:
                        raise ValueError("The scene job has exhausted its retry limit.")
                    cur.execute(
                        """
                        UPDATE jobs
                        SET status = 'queued', locked_at = NULL, error = NULL
                        WHERE job_id = %s
                        RETURNING job_id, status;
                        """,
                        (existing["job_id"],),
                    )
                    job = cur.fetchone()
                    return {
                        "job_id": job["job_id"],
                        "status": job["status"],
                        "created": False,
                    }
                return {
                    "job_id": existing["job_id"],
                    "status": status,
                    "created": False,
                }

            cur.execute(
                """
                INSERT INTO jobs (kind, scene_id, status)
                VALUES ('process_scene', %s, 'queued')
                RETURNING job_id, status;
                """,
                (scene_id,),
            )
            job = cur.fetchone()
            return {
                "job_id": job["job_id"],
                "status": job["status"],
                "created": True,
            }
