"""
Per-scene processing pipeline orchestrator.
Vercel Serverless Function & Python API for executing Phase 2 through Phase 6:
- Lock job
- Preprocess Sentinel-2 bands, cloud mask, water mask
- ONNX UNet inference & 14-channel stacking
- Debris polygon vectorization & quantification
- Patch tracking (Hungarian matching, splits P-NNNN-A/B, merges, born)
- Cloud status & clear evidence accumulation
- Forecast verification against observation
- 500-particle ensemble drift forecast (RK4, 24h/48h probability areas)
- First-passage zone risk evaluation (Advisory/Warning tiers)
- Alert generation into outbox
- Mark job done/failed
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from core.config import (
    CRON_SECRET,
    DEBRIS_PROB_THRESHOLD,
    INGEST_SECRET,
)
from core.api_utils import is_authorized
from core.db import get_db_connection, get_db_cursor, finish_job, lock_and_acquire_job
from core.preprocess import PreprocessedScene, preprocess_scene
from core.infer import run_debris_inference
from core.polygons import extract_debris_polygons
from core.tracking import (
    Detection,
    TrackedPatch,
    TrackingResult,
    track_scene_detections,
)
from core.cloudstatus import evaluate_unmatched_patch_status
from core.verify import (
    ForecastData,
    VerificationRecord,
    verify_forecast,
    verify_split_forecast,
)
from core.forecast import run_ensemble_forecast
from core.zonerisk import evaluate_zone_risk
from core.alerts import (
    generate_dedupe_key,
    should_trigger_alert,
    format_alert_payload,
    insert_alert,
)

logger = logging.getLogger(__name__)


def run_process_scene(
    scene_id: str,
    aoi_id: Optional[int] = None,
    bands: Optional[Dict[str, Any]] = None,
    aoi_bounds: Optional[Tuple[float, float, float, float]] = None,
    detections: Optional[List[Detection]] = None,
    scene_time: Optional[datetime] = None,
    job_id: Optional[int] = None,
    existing_patches: Optional[List[TrackedPatch]] = None,
    existing_forecasts: Optional[Dict[str, ForecastData]] = None,
    registered_zones: Optional[List[Dict[str, Any]]] = None,
    previous_alerts: Optional[Dict[Tuple[Union[int, str], str], Dict[str, Any]]] = None,
    inference_session: Optional[Any] = None,
    metocean: Optional[Any] = None,
    land_geom: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Execute full per-scene pipeline end-to-end.

    Returns a comprehensive result dictionary with:
      - scene_id
      - observations
      - tracking_result
      - cloud_events
      - verifications
      - new_forecasts
      - risk_evals
      - alerts
    """
    if scene_time is None:
        scene_time = datetime.now(timezone.utc)

    logger.info(f"Starting pipeline for scene {scene_id} at {scene_time.isoformat()}")

    try:
        if detections is None:
            # 1. Preprocessing
            if bands is None:
                from core.preprocess import REQUIRED_BANDS
                h, w = 256, 256
                bands = {b: np.full((h, w), 0.05, dtype=np.float32) for b in REQUIRED_BANDS}
                bands["B8"] = np.full((h, w), 0.06, dtype=np.float32)
                bands["B6"] = np.full((h, w), 0.05, dtype=np.float32)
                bands["B11"] = np.full((h, w), 0.05, dtype=np.float32)
                bands["SCL"] = np.full((h, w), 6, dtype=np.uint8)  # Water

            prep_scene = preprocess_scene(bands, aoi_bounds=aoi_bounds, scale_reflectance=False)

            # 2. Inference
            prob_map = run_debris_inference(
                prep_scene.bands,
                session=inference_session,
            )

            # 3. Polygon extraction
            obs_dicts = extract_debris_polygons(
                debris_prob=prob_map,
                water_mask=prep_scene.water_mask,
                cloud_mask=prep_scene.cloud_mask,
                fdi=prep_scene.ndwi,  # proxy/calculated FDI
                transform=prep_scene.transform,
                crs=prep_scene.crs,
                scene_id=scene_id,
                threshold=DEBRIS_PROB_THRESHOLD,
            )

            # Convert to Detection objects
            detections = []
            for i, o in enumerate(obs_dicts):
                det = Detection(
                    centroid=(o["centroid"]["coordinates"][0], o["centroid"]["coordinates"][1]),
                    area_m2=float(o["area_m2"]),
                    geom=o["geom"],
                    obs_id=i + 1,
                    confidence=float(o.get("confidence", 1.0)),
                    mean_fdi=float(o.get("mean_fdi", 0.0)),
                    cloud_overlap=float(o.get("cloud_overlap", 0.0)),
                    scene_id=scene_id,
                )
                detections.append(det)
        else:
            obs_dicts = [
                {
                    "centroid": {"type": "Point", "coordinates": list(d.centroid)},
                    "area_m2": d.area_m2,
                    "geom": d.geom,
                    "obs_id": d.obs_id or (i + 1),
                    "confidence": d.confidence,
                    "mean_fdi": d.mean_fdi,
                    "cloud_overlap": d.cloud_overlap,
                }
                for i, d in enumerate(detections)
            ]
            if bands is not None:
                prep_scene = preprocess_scene(bands, aoi_bounds=aoi_bounds, scale_reflectance=False)
            else:
                prep_scene = None

        # 4. Tracking
        candidate_patches = list(existing_patches) if existing_patches is not None else []
        if existing_forecasts:
            for p in candidate_patches:
                if p.patch_id in existing_forecasts:
                    fc = existing_forecasts[p.patch_id]
                    if p.ensemble_particles is None and fc.particles_at_scene is not None:
                        p.ensemble_particles = fc.particles_at_scene
                    if p.p90_geom is None and fc.p90_geom is not None:
                        p.p90_geom = fc.p90_geom

        tracking_res = track_scene_detections(
            patches=candidate_patches,
            detections=detections,
            scene_time=scene_time,
            scene_id=scene_id,
        )

        # 5. Cloud Status for unassigned patches
        cloud_events = []
        cloud_mask = prep_scene.cloud_mask if prep_scene is not None else None
        for p in tracking_res.unmatched_patches:
            evs = evaluate_unmatched_patch_status(
                patch=p,
                scene_time=scene_time,
                cloud_mask=cloud_mask,
                scene_id=scene_id,
            )
            cloud_events.extend(evs)

        # 6. Forecast Verification
        verifications: List[VerificationRecord] = []
        if existing_forecasts:
            # Standard matches
            for patch, det in tracking_res.matched:
                if patch.patch_id in existing_forecasts:
                    fc = existing_forecasts[patch.patch_id]
                    v_rec = verify_forecast(
                        forecast=fc,
                        detection=det,
                        scene_time=scene_time,
                        previous_obs_centroid=patch.last_centroid,
                    )
                    verifications.append(v_rec)

            # Splits
            for parent, children in tracking_res.splits:
                if parent.patch_id in existing_forecasts:
                    fc = existing_forecasts[parent.patch_id]
                    v_rec = verify_split_forecast(
                        parent_forecast=fc,
                        children_detections=children,
                        scene_time=scene_time,
                    )
                    verifications.append(v_rec)

        # 7. Drift Forecast (RK4 500-particle ensemble)
        new_forecasts: Dict[str, Dict[str, Any]] = {}

        # Run forecast for newly born patches
        for patch, det in tracking_res.new_patches:
            fc = run_ensemble_forecast(
                patch_id=patch.patch_id,
                seeded_from="observation",
                geometry=det.geom,
                t0=scene_time,
                metocean=metocean,
                land_geom=land_geom,
            )
            new_forecasts[patch.patch_id] = fc

        # Run forecast for matched patches (re-seed from new observation)
        for patch, det in tracking_res.matched:
            fc = run_ensemble_forecast(
                patch_id=patch.patch_id,
                seeded_from="observation",
                geometry=det.geom,
                t0=scene_time,
                metocean=metocean,
                land_geom=land_geom,
            )
            new_forecasts[patch.patch_id] = fc

        # Run forecast for split children (seeded from their respective fragment polygons)
        for parent, children in tracking_res.splits:
            for child_patch, child_det in children:
                fc = run_ensemble_forecast(
                    patch_id=child_patch.patch_id,
                    seeded_from="observation",
                    geometry=child_det.geom,
                    t0=scene_time,
                    metocean=metocean,
                    land_geom=land_geom,
                )
                new_forecasts[child_patch.patch_id] = fc

        # Run forecast for occluded patches (carry forward previous ensemble)
        for p in tracking_res.unmatched_patches:
            if p.status == "occluded":
                prev_fc = existing_forecasts.get(p.patch_id) if existing_forecasts else None
                prev_tracks = prev_fc.particles_at_scene if prev_fc else None
                fc = run_ensemble_forecast(
                    patch_id=p.patch_id,
                    seeded_from="ensemble",
                    prev_tracks=prev_tracks,
                    t0=scene_time,
                    metocean=metocean,
                    land_geom=land_geom,
                    centroid=p.last_centroid,
                )
                new_forecasts[p.patch_id] = fc

        # 8. Zone Risk Evaluation
        risk_evals: List[Dict[str, Any]] = []
        zones = registered_zones or []
        for patch_id, fc in new_forecasts.items():
            tracks = fc["tracks"]
            for z in zones:
                eval_res = evaluate_zone_risk(
                    tracks=tracks,
                    zone=z,
                    t0=scene_time,
                    window_hours=48,
                    forecast_id=fc["forecast"]["forecast_id"],
                    patch_id=patch_id,
                )
                risk_evals.append(eval_res)

        # 9. Alert Generation & Deduplication
        generated_alerts: List[Dict[str, Any]] = []
        prev_alerts_map = previous_alerts or {}

        for r in risk_evals:
            zone_id = r["zone_id"]
            patch_id = r["patch_id"]
            curr_tier = r["tier"]
            curr_p = r["p_reach"]

            # Lookup prior alert for this zone & patch
            prev_alert = prev_alerts_map.get((zone_id, patch_id))
            prev_tier = prev_alert.get("tier", "None") if prev_alert else "None"
            prev_p = prev_alert.get("p_reach", 0.0) if prev_alert else 0.0

            if should_trigger_alert(curr_tier, curr_p, prev_alert):
                # Find patch status and matching zone info
                patch_obj = next(
                    (p for p in candidate_patches if p.patch_id == patch_id),
                    None
                )
                patch_status = patch_obj.status if patch_obj else "active"
                zone_obj = next((z for z in zones if z.get("zone_id") == zone_id), {})
                zone_name = zone_obj.get("name", f"Zone {zone_id}")

                payload = format_alert_payload(
                    patch_id=patch_id,
                    zone_name=zone_name,
                    tier=curr_tier,
                    probability=curr_p,
                    eta_p10=r["eta_p10"],
                    eta_p90=r["eta_p90"],
                    patch_status=patch_status,
                    last_observed_utc=scene_time,
                    scene_id=scene_id,
                )

                dedupe_key = generate_dedupe_key(
                    zone_id=zone_id,
                    patch_id=patch_id,
                    scene_id=scene_id,
                    tier=curr_tier,
                )

                alert_record = {
                    "dedupe_key": dedupe_key,
                    "zone_id": zone_id,
                    "patch_id": patch_id,
                    "scene_id": scene_id,
                    "tier": curr_tier,
                    "p_reach": curr_p,
                    "eta_start": r["eta_p10"],
                    "eta_end": r["eta_p90"],
                    "payload": payload,
                    "channel": "all",
                    "status": "pending",
                    "attempts": 0,
                    "next_attempt_at": datetime.now(timezone.utc),
                }
                generated_alerts.append(alert_record)
                insert_alert(alert_record)

        # 10. Mark Job as Done if job_id provided
        if job_id is not None:
            finish_job(job_id=job_id, status="done")

        return {
            "status": "success",
            "scene_id": scene_id,
            "observations_count": len(obs_dicts),
            "observations": obs_dicts,
            "tracking_result": tracking_res,
            "cloud_events": cloud_events,
            "verifications": verifications,
            "new_forecasts": new_forecasts,
            "risk_evals": risk_evals,
            "alerts": generated_alerts,
        }

    except Exception as e:
        logger.error(f"Error executing pipeline for scene {scene_id}: {e}", exc_info=True)
        if job_id is not None:
            finish_job(job_id=job_id, status="failed", error=str(e))
        raise


class handler(BaseHTTPRequestHandler):
    """Vercel Serverless Function HTTP Handler."""

    def do_POST(self):
        # 1. Verify Secret
        if not is_authorized(self.headers, CRON_SECRET, INGEST_SECRET):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Unauthorized"}).encode("utf-8"))
            return

        # 2. Parse Payload
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"

        try:
            payload = json.loads(body.decode("utf-8"))
            scene_id = payload.get("scene_id")
            aoi_id = payload.get("aoi_id")
            job_id = payload.get("job_id")

            if not scene_id:
                # Try acquiring next queued job from database
                locked_job = lock_and_acquire_job()
                if locked_job:
                    scene_id = locked_job["scene_id"]
                    job_id = locked_job["job_id"]
                    if aoi_id is None:
                        aoi_id = locked_job.get("aoi_id")
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "no_queued_jobs"}).encode("utf-8"))
                    return

            result = run_process_scene(scene_id=scene_id, aoi_id=aoi_id, job_id=job_id)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "status": "done",
                        "scene_id": scene_id,
                        "observations_count": result["observations_count"],
                        "alerts_count": len(result["alerts"]),
                    }
                ).encode("utf-8")
            )

        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "error": str(e)}).encode("utf-8"))
