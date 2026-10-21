"""
Database helper module for Neon Postgres + PostGIS using psycopg 3.
Provides connection pooling, transaction context managers, and job row-locking.
"""

import contextlib
import logging
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
                    SELECT job_id, kind, scene_id, status, attempts
                    FROM jobs
                    WHERE job_id = %s AND status = 'queued'
                    FOR UPDATE SKIP LOCKED;
                    """,
                    (job_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT job_id, kind, scene_id, status, attempts
                    FROM jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED;
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
