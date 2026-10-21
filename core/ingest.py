"""
Data ingestion module for Sentinel-2 MSI data.
Handles:
- STAC queries (Earth Search AWS or CDSE) via pystac_client with offline deterministic fallback
- Extraction of band asset COG URLs (B1..B12, SCL)
- Idempotency checks against the `scenes` database table
- Scene registration in the database
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import shapely.geometry

logger = logging.getLogger(__name__)

DEFAULT_STAC_URL = "https://earth-search.aws.element84.com/v1"
SENTINEL_COLLECTIONS = ["sentinel-2-l2a", "sentinel-2-c1-l2a"]

# Mapping of standard band names to alternative STAC asset keys
ASSET_KEY_CANDIDATES = {
    "B1": ["B01", "b01", "coastal", "B1", "b1"],
    "B2": ["B02", "b02", "blue", "B2", "b2"],
    "B3": ["B03", "b03", "green", "B3", "b3"],
    "B4": ["B04", "b04", "red", "B4", "b4"],
    "B5": ["B05", "b05", "rededge1", "B5", "b5"],
    "B6": ["B06", "b06", "rededge2", "B6", "b6"],
    "B7": ["B07", "b07", "rededge3", "B7", "b7"],
    "B8": ["B08", "b08", "nir", "B8", "b8"],
    "B8A": ["B8A", "b8a", "B08A", "b08a", "nir08", "nir09"],
    "B11": ["B11", "b11", "swir16", "swir1"],
    "B12": ["B12", "b12", "swir22", "swir2"],
    "SCL": ["SCL", "scl", "visual", "aot-scl"],
}


def make_deterministic_mock_scene(
    aoi_geom: Optional[Any] = None,
    start_date: str = "2026-10-21",
    end_date: str = "2026-10-21",
    cloud_frac: float = 0.05,
    aoi_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Generate deterministic mock scene metadata and asset URLs
    when STAC endpoint is unreachable or in offline/test environments.
    """
    date_slug = start_date.replace("-", "").replace(":", "")[:8]
    scene_id = f"S2A_MSIL2A_{date_slug}T103021_N0500_R108_T31UFT"
    sensing_time = f"{start_date}T10:30:21Z" if "T" not in start_date else start_date

    assets = {
        band: f"mock://sentinel-2/{scene_id}_{band}.tif"
        for band in ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12", "SCL"]
    }

    if aoi_geom is not None:
        try:
            poly = shapely.geometry.shape(aoi_geom) if isinstance(aoi_geom, dict) else aoi_geom
            bbox = list(poly.bounds)
        except Exception:
            bbox = [10.0, 50.0, 10.5, 50.5]
    else:
        bbox = [10.0, 50.0, 10.5, 50.5]

    return {
        "scene_id": scene_id,
        "aoi_id": aoi_id,
        "sensing_time": sensing_time,
        "cloud_frac": float(cloud_frac),
        "source": "deterministic_mock",
        "assets": assets,
        "bbox": bbox,
        "crs": "EPSG:4326",
    }


def query_stac_scene(
    aoi_geom: Any,
    start_date: str,
    end_date: str,
    max_cloud: float = 0.8,
    stac_endpoint: str = DEFAULT_STAC_URL,
    aoi_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Query STAC endpoint for Sentinel-2 L2A scene covering an AOI within a datetime range.
    Falls back to deterministic mock metadata if offline or query fails.
    """
    try:
        from pystac_client import Client

        client = Client.open(stac_endpoint, timeout=10.0)

        # Convert geometry to GeoJSON dict if shapely
        if hasattr(aoi_geom, "__geo_interface__"):
            geom_dict = aoi_geom.__geo_interface__
        elif isinstance(aoi_geom, dict):
            geom_dict = aoi_geom
        else:
            geom_dict = shapely.geometry.mapping(aoi_geom)

        dt_param = (
            f"{start_date}/{end_date}"
            if start_date != end_date
            else f"{start_date}T00:00:00Z/{end_date}T23:59:59Z"
        )

        search = client.search(
            collections=SENTINEL_COLLECTIONS,
            intersects=geom_dict,
            datetime=dt_param,
            query={"eo:cloud_cover": {"lt": max_cloud * 100.0}},
            limit=5,
        )

        items = list(search.items())
        if not items:
            logger.info(
                f"No STAC items returned for range {dt_param}; returning deterministic mock."
            )
            return make_deterministic_mock_scene(
                aoi_geom=aoi_geom,
                start_date=start_date,
                end_date=end_date,
                aoi_id=aoi_id,
            )

        # Sort by cloud cover and take lowest cloud scene
        items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 100.0))
        item = items[0]

        # Map asset URLs
        assets: Dict[str, str] = {}
        for target_band, candidates in ASSET_KEY_CANDIDATES.items():
            for cand in candidates:
                if cand in item.assets:
                    assets[target_band] = item.assets[cand].href
                    break

        cloud_cover_pct = item.properties.get("eo:cloud_cover", 0.0)
        sensing_time = (
            item.datetime.isoformat()
            if item.datetime
            else item.properties.get("datetime", "")
        )

        return {
            "scene_id": item.id,
            "aoi_id": aoi_id,
            "sensing_time": sensing_time,
            "cloud_frac": float(cloud_cover_pct) / 100.0,
            "source": "stac_query",
            "assets": assets,
            "bbox": item.bbox,
            "crs": "EPSG:4326",
        }

    except Exception as e:
        logger.info(
            f"STAC query failed or offline ({e}); returning deterministic mock scene."
        )
        return make_deterministic_mock_scene(
            aoi_geom=aoi_geom,
            start_date=start_date,
            end_date=end_date,
            cloud_frac=0.05,
            aoi_id=aoi_id,
        )


def check_scene_exists(scene_id: str) -> bool:
    """
    Idempotency check: returns True if scene_id already exists in the scenes table.
    """
    try:
        from core.db import get_db_cursor

        with get_db_cursor() as cur:
            cur.execute("SELECT 1 FROM scenes WHERE scene_id = %s LIMIT 1;", (scene_id,))
            row = cur.fetchone()
            return row is not None
    except Exception as e:
        logger.debug(f"Database unavailable for check_scene_exists: {e}")
        return False


def register_scene(
    scene_id: str,
    aoi_id: Optional[int] = None,
    sensing_time: Optional[Union[str, datetime]] = None,
    source: str = "poll",
    cloud_frac: float = 0.0,
    status: str = "queued",
) -> bool:
    """
    Register a scene in the `scenes` database table.
    Uses ON CONFLICT (scene_id) DO NOTHING for idempotency.
    """
    try:
        from core.db import get_db_cursor

        with get_db_cursor() as cur:
            cur.execute(
                """
                INSERT INTO scenes (scene_id, aoi_id, sensing_time, source, cloud_frac, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (scene_id) DO NOTHING;
                """,
                (scene_id, aoi_id, sensing_time, source, cloud_frac, status),
            )
            return True
    except Exception as e:
        logger.debug(f"Database unavailable for register_scene: {e}")
        return False
