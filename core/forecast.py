"""
Ensemble drift physics forecasting engine for Multispectral Ocean Debris Tracking.
Implements 500-particle stochastic RK4 drift simulation, met-ocean coupling,
land collision (beaching), and 24h/48h probability area KDE contours.
Conforms to plan.md Sections 8, 9.5 and execution_plan.md Phase 5.
"""

import os
import math
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union

import numpy as np
import scipy.stats
from scipy.stats import truncnorm
import shapely
from shapely.geometry import Point, Polygon, MultiPolygon, shape
import rasterio.features
import affine

from core.config import (
    ENSEMBLE_PARTICLES,
    FORECAST_HOURS,
    FORECAST_TIME_STEP_HOURS,
    WINDAGE_MEAN,
    WINDAGE_STD,
    WINDAGE_MIN,
    WINDAGE_MAX,
    LEEWAY_ANGLE_MEAN_DEG,
    LEEWAY_ANGLE_STD_DEG,
    CURRENT_SCALE_MEAN,
    CURRENT_SCALE_STD,
    DIFFUSION_COEFF_K,
    PROBABILITY_HORIZONS_H,
    PROBABILITY_LEVELS,
    BLOB_READ_WRITE_TOKEN,
)

logger = logging.getLogger(__name__)

# Geodesic conversion constants
METERS_PER_DEG_LAT = 111320.0


# ---------------------------------------------------------------------------
# 1. Seeding Particles
# ---------------------------------------------------------------------------

def _to_shapely_geometry(geom: Any) -> Any:
    """Normalize geometry to a Shapely geometry object."""
    if isinstance(geom, (Polygon, MultiPolygon, Point)):
        return geom
    if isinstance(geom, dict):
        return shape(geom)
    if isinstance(geom, str):
        import shapely.wkt
        return shapely.wkt.loads(geom)
    raise ValueError(f"Unsupported geometry type: {type(geom)}")


def seed_particles(
    geometry: Optional[Any] = None,
    seeded_from: str = "observation",
    prev_tracks: Optional[np.ndarray] = None,
    t0: Optional[datetime] = None,
    prev_t0: Optional[datetime] = None,
    n_particles: int = ENSEMBLE_PARTICLES,
    rng: Optional[np.random.Generator] = None,
) -> np.ndarray:
    """
    Seed initial ensemble particle locations (shape: (n_particles, 2) [lon, lat]).

    If seeded_from == 'observation':
      Seeds particles uniformly inside the observed polygon geometry
      (or clustered around centroid if small/point).
    If seeded_from == 'ensemble':
      Carries forward particles from previous forecast valid at time t0.
    """
    if rng is None:
        rng = np.random.default_rng()

    if seeded_from == "ensemble":
        if prev_tracks is None:
            if geometry is not None:
                return seed_particles(geometry=geometry, seeded_from="observation", n_particles=n_particles, rng=rng)
            raise ValueError("prev_tracks must be provided when seeded_from == 'ensemble'")

        # If prev_tracks is 3D (particles, timesteps, 2)
        if prev_tracks.ndim == 3:
            if t0 is not None and prev_t0 is not None:
                step = int(round((t0 - prev_t0).total_seconds() / 3600.0))
                step = max(0, min(step, prev_tracks.shape[1] - 1))
            else:
                step = -1  # Default to latest step
            particles = prev_tracks[:, step, :2].copy()
        elif prev_tracks.ndim == 2:
            particles = prev_tracks[:, :2].copy()
        else:
            raise ValueError(f"prev_tracks has invalid shape: {prev_tracks.shape}")

        # Resample to match n_particles if different
        if particles.shape[0] != n_particles:
            indices = rng.choice(particles.shape[0], size=n_particles, replace=True)
            particles = particles[indices]

        return particles.astype(np.float32)

    elif seeded_from == "observation":
        if geometry is None:
            raise ValueError("geometry must be provided when seeded_from == 'observation'")

        geom = _to_shapely_geometry(geometry)

        # Handle Point geometry
        if isinstance(geom, Point):
            centroid_lon, centroid_lat = geom.x, geom.y
            jitter_deg = 50.0 / METERS_PER_DEG_LAT  # ~50m jitter
            lons = rng.normal(centroid_lon, jitter_deg, size=n_particles)
            lats = rng.normal(centroid_lat, jitter_deg, size=n_particles)
            return np.column_stack([lons, lats]).astype(np.float32)

        # Handle Polygon / MultiPolygon
        if isinstance(geom, (Polygon, MultiPolygon)):
            minx, miny, maxx, maxy = geom.bounds
            width = maxx - minx
            height = maxy - miny

            # If degenerate or tiny polygon (e.g., smaller than 5m)
            if width < 1e-5 or height < 1e-5 or geom.area < 1e-10:
                c = geom.centroid
                jitter_deg = 20.0 / METERS_PER_DEG_LAT
                lons = rng.normal(c.x, jitter_deg, size=n_particles)
                lats = rng.normal(c.y, jitter_deg, size=n_particles)
                return np.column_stack([lons, lats]).astype(np.float32)

            # Rejection sampling uniformly inside the polygon bounds
            collected_pts: List[np.ndarray] = []
            total_collected = 0
            batch_size = max(n_particles * 2, 1000)
            max_iter = 50
            iteration = 0

            while total_collected < n_particles and iteration < max_iter:
                iteration += 1
                cand_xs = rng.uniform(minx, maxx, batch_size)
                cand_ys = rng.uniform(miny, maxy, batch_size)

                # Vectorized point-in-polygon test via Shapely 2.x contains_xy
                mask = shapely.contains_xy(geom, cand_xs, cand_ys)
                valid_pts = np.column_stack([cand_xs[mask], cand_ys[mask]])
                if len(valid_pts) > 0:
                    collected_pts.append(valid_pts)
                    total_collected += len(valid_pts)

            if total_collected >= n_particles:
                all_pts = np.vstack(collected_pts)
                return all_pts[:n_particles].astype(np.float32)

            # Fallback if complex narrow geometry: jitter around centroid
            c = geom.centroid
            jitter_deg = max(width, height, 50.0 / METERS_PER_DEG_LAT) * 0.25
            lons = rng.normal(c.x, jitter_deg, size=n_particles)
            lats = rng.normal(c.y, jitter_deg, size=n_particles)
            return np.column_stack([lons, lats]).astype(np.float32)

        raise ValueError(f"Unsupported geometry type for observation seeding: {type(geom)}")

    else:
        raise ValueError(f"Invalid seeded_from value: {seeded_from}. Expected 'observation' or 'ensemble'.")


# ---------------------------------------------------------------------------
# 2. Stochastic Particle Parameters
# ---------------------------------------------------------------------------

def draw_particle_parameters(
    n_particles: int = ENSEMBLE_PARTICLES,
    rng: Optional[np.random.Generator] = None,
) -> Dict[str, np.ndarray]:
    """
    Draw stochastic drift parameters for each ensemble particle:
    - Windage: truncated normal in [WINDAGE_MIN, WINDAGE_MAX] with mean 0.02, std 0.007
    - Leeway deflection angle: normal with mean 0 deg, std 10 deg
    - Current scale factor: normal with mean 1.0, std 0.15
    """
    # Truncated normal parameters for windage
    a = (WINDAGE_MIN - WINDAGE_MEAN) / WINDAGE_STD
    b = (WINDAGE_MAX - WINDAGE_MEAN) / WINDAGE_STD

    # Generate truncated normal samples
    windage = truncnorm.rvs(
        a, b,
        loc=WINDAGE_MEAN,
        scale=WINDAGE_STD,
        size=n_particles,
        random_state=rng,
    ).astype(np.float32)

    if rng is None:
        rng = np.random.default_rng()

    # Leeway angle in degrees and radians
    leeway_deg = rng.normal(
        loc=LEEWAY_ANGLE_MEAN_DEG,
        scale=LEEWAY_ANGLE_STD_DEG,
        size=n_particles,
    ).astype(np.float32)
    leeway_rad = np.radians(leeway_deg).astype(np.float32)

    # Current scaling factor
    current_scale = rng.normal(
        loc=CURRENT_SCALE_MEAN,
        scale=CURRENT_SCALE_STD,
        size=n_particles,
    ).astype(np.float32)

    return {
        "windage": windage,
        "leeway_angle_deg": leeway_deg,
        "leeway_angle_rad": leeway_rad,
        "current_scale": current_scale,
    }


# ---------------------------------------------------------------------------
# 3. Met-Ocean Environmental Fields
# ---------------------------------------------------------------------------

class MetOceanField:
    """
    Represents time- and space-varying wind (10m) and ocean current velocity fields.
    Supports either interpolated gridded time series or deterministic synthetic fields.
    """

    def __init__(
        self,
        is_synthetic: bool = True,
        synthetic_u_curr: float = 0.25,
        synthetic_v_curr: float = 0.05,
        synthetic_u_wind: float = 4.0,
        synthetic_v_wind: float = 1.5,
        time_series: Optional[Dict[str, np.ndarray]] = None,
        **kwargs,
    ):
        if "u_current" in kwargs:
            synthetic_u_curr = kwargs["u_current"]
        if "v_current" in kwargs:
            synthetic_v_curr = kwargs["v_current"]
        if "u_wind" in kwargs:
            synthetic_u_wind = kwargs["u_wind"]
        if "v_wind" in kwargs:
            synthetic_v_wind = kwargs["v_wind"]

        self.is_synthetic = is_synthetic
        self.synthetic_u_curr = synthetic_u_curr
        self.synthetic_v_curr = synthetic_v_curr
        self.synthetic_u_wind = synthetic_u_wind
        self.synthetic_v_wind = synthetic_v_wind
        self.time_series = time_series or {}

    def get_current(
        self, lons: np.ndarray, lats: np.ndarray, t_hour: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return ocean current velocity (u, v) in m/s at given locations and time."""
        if self.is_synthetic or "curr_u" not in self.time_series:
            # Deterministic synthetic current field
            u = np.full_like(lons, self.synthetic_u_curr, dtype=np.float32)
            v = np.full_like(lats, self.synthetic_v_curr, dtype=np.float32)
            return u, v

        # Interpolate from 1D hourly time series
        hours = self.time_series.get("hours", np.arange(len(self.time_series["curr_u"])))
        u_val = float(np.interp(t_hour, hours, self.time_series["curr_u"]))
        v_val = float(np.interp(t_hour, hours, self.time_series["curr_v"]))
        u = np.full_like(lons, u_val, dtype=np.float32)
        v = np.full_like(lats, v_val, dtype=np.float32)
        return u, v

    def get_wind(
        self, lons: np.ndarray, lats: np.ndarray, t_hour: float
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Return wind velocity (u, v) in m/s at given locations and time."""
        if self.is_synthetic or "wind_u" not in self.time_series:
            # Deterministic synthetic wind field
            u = np.full_like(lons, self.synthetic_u_wind, dtype=np.float32)
            v = np.full_like(lats, self.synthetic_v_wind, dtype=np.float32)
            return u, v

        # Interpolate from 1D hourly time series
        hours = self.time_series.get("hours", np.arange(len(self.time_series["wind_u"])))
        u_val = float(np.interp(t_hour, hours, self.time_series["wind_u"]))
        v_val = float(np.interp(t_hour, hours, self.time_series["wind_v"]))
        u = np.full_like(lons, u_val, dtype=np.float32)
        v = np.full_like(lats, v_val, dtype=np.float32)
        return u, v


def fetch_metocean_forecast(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    t0: Optional[datetime] = None,
    hours: int = FORECAST_HOURS,
    use_synthetic: bool = False,
    synthetic_u_curr: float = 0.25,
    synthetic_v_curr: float = 0.05,
    synthetic_u_wind: float = 4.0,
    synthetic_v_wind: float = 1.5,
) -> MetOceanField:
    """
    Fetch wind and ocean currents from Open-Meteo API.
    Gracefully falls back to deterministic synthetic fields if offline or network error.
    """
    if use_synthetic:
        return MetOceanField(
            is_synthetic=True,
            synthetic_u_curr=synthetic_u_curr,
            synthetic_v_curr=synthetic_v_curr,
            synthetic_u_wind=synthetic_u_wind,
            synthetic_v_wind=synthetic_v_wind,
        )

    mid_lat = (min_lat + max_lat) / 2.0
    mid_lon = (min_lon + max_lon) / 2.0

    try:
        import requests

        forecast_days = min(16, max(1, int(math.ceil(hours / 24.0)) + 1))

        # 1. Fetch wind from Open-Meteo Weather API
        weather_url = "https://api.open-meteo.com/v1/forecast"
        weather_params = {
            "latitude": mid_lat,
            "longitude": mid_lon,
            "hourly": "wind_speed_10m,wind_direction_10m",
            "forecast_days": forecast_days,
        }
        w_resp = requests.get(weather_url, params=weather_params, timeout=4.0)
        w_resp.raise_for_status()
        w_data = w_resp.json()

        w_hourly = w_data.get("hourly", {})
        raw_wind_speeds = [v if v is not None else 0.0 for v in w_hourly.get("wind_speed_10m", [])]
        raw_wind_dirs = [v if v is not None else 0.0 for v in w_hourly.get("wind_direction_10m", [])]
        wind_speeds = np.array(raw_wind_speeds, dtype=np.float32) / 3.6  # km/h to m/s
        wind_dirs = np.array(raw_wind_dirs, dtype=np.float32)

        # Meteorology: wind direction is direction wind comes FROM -> drift is in direction -dir
        wind_rad = np.radians(wind_dirs)
        wind_u = np.nan_to_num(-wind_speeds * np.sin(wind_rad), nan=0.0)
        wind_v = np.nan_to_num(-wind_speeds * np.cos(wind_rad), nan=0.0)

        # 2. Fetch ocean currents from Open-Meteo Marine API
        marine_url = "https://marine-api.open-meteo.com/v1/marine"
        marine_params = {
            "latitude": mid_lat,
            "longitude": mid_lon,
            "hourly": "ocean_current_velocity,ocean_current_direction",
            "forecast_days": forecast_days,
        }
        m_resp = requests.get(marine_url, params=marine_params, timeout=4.0)
        m_resp.raise_for_status()
        m_data = m_resp.json()

        m_hourly = m_data.get("hourly", {})
        raw_curr_speeds = [v if v is not None else synthetic_u_curr for v in m_hourly.get("ocean_current_velocity", [])]
        raw_curr_dirs = [v if v is not None else 0.0 for v in m_hourly.get("ocean_current_direction", [])]
        curr_speeds = np.array(raw_curr_speeds, dtype=np.float32) / 3.6  # km/h to m/s
        curr_dirs = np.array(raw_curr_dirs, dtype=np.float32)

        # Oceanography: current direction is direction current flows TOWARDS
        curr_rad = np.radians(curr_dirs)
        curr_u = np.nan_to_num(curr_speeds * np.sin(curr_rad), nan=synthetic_u_curr)
        curr_v = np.nan_to_num(curr_speeds * np.cos(curr_rad), nan=synthetic_v_curr)

        n_steps = min(len(wind_u), len(curr_u), hours + 1)
        if n_steps > 1:
            time_series = {
                "hours": np.arange(n_steps, dtype=np.float32),
                "wind_u": wind_u[:n_steps],
                "wind_v": wind_v[:n_steps],
                "curr_u": curr_u[:n_steps],
                "curr_v": curr_v[:n_steps],
            }
            logger.info("Successfully fetched live Met-Ocean data from Open-Meteo.")
            return MetOceanField(is_synthetic=False, time_series=time_series)

    except Exception as e:
        logger.warning(f"Met-Ocean API fetch failed or offline ({e}). Using deterministic synthetic field.")

    return MetOceanField(
        is_synthetic=True,
        synthetic_u_curr=synthetic_u_curr,
        synthetic_v_curr=synthetic_v_curr,
        synthetic_u_wind=synthetic_u_wind,
        synthetic_v_wind=synthetic_v_wind,
    )


# ---------------------------------------------------------------------------
# 4. RK4 Drift Integration
# ---------------------------------------------------------------------------

def integrate_rk4(
    particles_init: np.ndarray,
    metocean: MetOceanField,
    params: Dict[str, np.ndarray],
    hours: int = FORECAST_HOURS,
    dt_seconds: float = 3600.0,
    land_geom: Optional[Any] = None,
    rng: Optional[np.random.Generator] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Runge-Kutta 4th-order drift integration over given hours (1h time step).

    Velocity:
      v_total = c_scale * v_current + w_windage * R(theta_leeway) * v_wind
    Diffusion:
      Step size: sigma = sqrt(2 * K * dt), added at each time step.
    Land collision:
      Particles reaching land stop and are marked beached.

    Returns:
      tracks: np.ndarray of shape (n_particles, hours + 1, 2) [lon, lat] float32
      beached_mask: np.ndarray of shape (n_particles,) bool
    """
    if rng is None:
        rng = np.random.default_rng()

    n_particles = particles_init.shape[0]
    total_steps = int(round(hours * 3600.0 / dt_seconds))

    tracks = np.zeros((n_particles, total_steps + 1, 2), dtype=np.float32)
    tracks[:, 0, :] = particles_init

    beached_mask = np.zeros(n_particles, dtype=bool)

    # Parameters
    windage = params["windage"]
    cos_leeway = np.cos(params["leeway_angle_rad"])
    sin_leeway = np.sin(params["leeway_angle_rad"])
    current_scale = params["current_scale"]

    # Diffusion step standard deviation in meters
    diffusion_sigma_m = math.sqrt(2.0 * DIFFUSION_COEFF_K * dt_seconds)

    # Optional prepared land geometry
    prep_land = None
    if land_geom is not None:
        prep_land = shapely.prepared.prep(_to_shapely_geometry(land_geom))
        # Initial check for particles starting on land
        init_beached = shapely.contains_xy(land_geom, particles_init[:, 0], particles_init[:, 1])
        beached_mask |= init_beached

    def compute_velocity(pos: np.ndarray, t_h: float) -> Tuple[np.ndarray, np.ndarray]:
        """Compute particle velocity in degrees/second for lat and lon."""
        lons = pos[:, 0]
        lats = pos[:, 1]

        u_curr, v_curr = metocean.get_current(lons, lats, t_h)
        u_wind, v_wind = metocean.get_wind(lons, lats, t_h)

        # Rotate wind by leeway angle
        u_wind_rot = u_wind * cos_leeway - v_wind * sin_leeway
        v_wind_rot = u_wind * sin_leeway + v_wind * cos_leeway

        # Combined drift velocity in m/s
        u_tot = current_scale * u_curr + windage * u_wind_rot
        v_tot = current_scale * v_curr + windage * v_wind_rot

        # Convert to degrees per second
        # dlat/dt = v / METERS_PER_DEG_LAT
        # dlon/dt = u / (METERS_PER_DEG_LAT * cos(lat))
        cos_lats = np.clip(np.cos(np.radians(lats)), 0.05, 1.0)
        dlat_dt = v_tot / METERS_PER_DEG_LAT
        dlon_dt = u_tot / (METERS_PER_DEG_LAT * cos_lats)

        return dlon_dt, dlat_dt

    curr_pos = particles_init.copy()

    for step in range(total_steps):
        t_h = float(step * dt_seconds / 3600.0)
        dt_h = float(dt_seconds / 3600.0)

        # RK4 advection calculation
        k1_lon, k1_lat = compute_velocity(curr_pos, t_h)

        pos_k2 = np.column_stack([
            curr_pos[:, 0] + 0.5 * dt_seconds * k1_lon,
            curr_pos[:, 1] + 0.5 * dt_seconds * k1_lat,
        ])
        k2_lon, k2_lat = compute_velocity(pos_k2, t_h + 0.5 * dt_h)

        pos_k3 = np.column_stack([
            curr_pos[:, 0] + 0.5 * dt_seconds * k2_lon,
            curr_pos[:, 1] + 0.5 * dt_seconds * k2_lat,
        ])
        k3_lon, k3_lat = compute_velocity(pos_k3, t_h + 0.5 * dt_h)

        pos_k4 = np.column_stack([
            curr_pos[:, 0] + dt_seconds * k3_lon,
            curr_pos[:, 1] + dt_seconds * k3_lat,
        ])
        k4_lon, k4_lat = compute_velocity(pos_k4, t_h + dt_h)

        dlon_advect = (dt_seconds / 6.0) * (k1_lon + 2.0 * k2_lon + 2.0 * k3_lon + k4_lon)
        dlat_advect = (dt_seconds / 6.0) * (k1_lat + 2.0 * k2_lat + 2.0 * k3_lat + k4_lat)

        # Diffusion random walk in meters -> degrees
        dx_m = rng.normal(0.0, diffusion_sigma_m, size=n_particles)
        dy_m = rng.normal(0.0, diffusion_sigma_m, size=n_particles)

        cos_lats = np.clip(np.cos(np.radians(curr_pos[:, 1])), 0.05, 1.0)
        dlon_diff = dx_m / (METERS_PER_DEG_LAT * cos_lats)
        dlat_diff = dy_m / METERS_PER_DEG_LAT

        # Propose new position
        new_lons = curr_pos[:, 0] + dlon_advect + dlon_diff
        new_lats = curr_pos[:, 1] + dlat_advect + dlat_diff

        # Check land collision for un-beached particles
        if land_geom is not None and not np.all(beached_mask):
            unbeached_indices = np.where(~beached_mask)[0]
            cand_lons = new_lons[unbeached_indices]
            cand_lats = new_lats[unbeached_indices]

            hits = shapely.contains_xy(land_geom, cand_lons, cand_lats)
            newly_beached = unbeached_indices[hits]
            if len(newly_beached) > 0:
                beached_mask[newly_beached] = True

        # Beached particles do not move
        new_lons[beached_mask] = curr_pos[beached_mask, 0]
        new_lats[beached_mask] = curr_pos[beached_mask, 1]

        curr_pos[:, 0] = new_lons
        curr_pos[:, 1] = new_lats
        tracks[:, step + 1, :] = curr_pos

    return tracks, beached_mask


# ---------------------------------------------------------------------------
# 5. Probability Areas via 2D Gaussian KDE
# ---------------------------------------------------------------------------

def compute_probability_areas(
    tracks: np.ndarray,
    horizon_h: int = 24,
    grid_res_km: float = 1.0,
) -> Dict[str, Any]:
    """
    Estimate 2D Gaussian KDE of particle cloud at horizon_h on a 1 km grid.
    Extract highest-density 50% and 90% contour polygons (MultiPolygon).
    Returns dict with horizon_h, centroid (Point), p50 (MultiPolygon), p90 (MultiPolygon).
    """
    if horizon_h >= tracks.shape[1]:
        raise ValueError(f"horizon_h ({horizon_h}) exceeds available track steps ({tracks.shape[1] - 1})")

    pts = tracks[:, horizon_h, :]  # shape: (n_particles, 2) [lon, lat]
    valid = np.isfinite(pts[:, 0]) & np.isfinite(pts[:, 1])
    if not np.all(valid):
        pts = pts[valid]
    if len(pts) < 3:
        c_lon = 0.0 if len(pts) == 0 else float(np.mean(pts[:, 0]))
        c_lat = 0.0 if len(pts) == 0 else float(np.mean(pts[:, 1]))
        r_50 = (500.0 / METERS_PER_DEG_LAT)
        r_90 = (1000.0 / METERS_PER_DEG_LAT)
        return {
            "horizon_h": horizon_h,
            "centroid": Point(c_lon, c_lat),
            "p50": MultiPolygon([Point(c_lon, c_lat).buffer(r_50)]),
            "p90": MultiPolygon([Point(c_lon, c_lat).buffer(r_90)]),
        }

    lons = pts[:, 0]
    lats = pts[:, 1]

    centroid = Point(float(np.mean(lons)), float(np.mean(lats)))

    # Compute variance / range
    var_lon = float(np.var(lons))
    var_lat = float(np.var(lats))

    # Fallback if particle cloud is collapsed to a point
    if var_lon < 1e-10 or var_lat < 1e-10:
        c_lon, c_lat = centroid.x, centroid.y
        r_50 = (500.0 / METERS_PER_DEG_LAT)  # 500m radius
        r_90 = (1000.0 / METERS_PER_DEG_LAT)
        p50 = MultiPolygon([Point(c_lon, c_lat).buffer(r_50)])
        p90 = MultiPolygon([Point(c_lon, c_lat).buffer(r_90)])
        return {"horizon_h": horizon_h, "centroid": centroid, "p50": p50, "p90": p90}

    # Gaussian KDE with fallback on singular covariance
    try:
        kde = scipy.stats.gaussian_kde(np.vstack([lons, lats]))
    except Exception:
        c_lon, c_lat = centroid.x, centroid.y
        r_50 = (500.0 / METERS_PER_DEG_LAT)
        r_90 = (1000.0 / METERS_PER_DEG_LAT)
        p50 = MultiPolygon([Point(c_lon, c_lat).buffer(r_50)])
        p90 = MultiPolygon([Point(c_lon, c_lat).buffer(r_90)])
        return {"horizon_h": horizon_h, "centroid": centroid, "p50": p50, "p90": p90}

    # Grid bounding box with padding
    mid_lat = float(np.mean(lats))
    res_lat = grid_res_km / (METERS_PER_DEG_LAT / 1000.0)  # degrees lat
    res_lon = grid_res_km / ((METERS_PER_DEG_LAT * max(math.cos(math.radians(mid_lat)), 0.05)) / 1000.0)

    pad_lon = 5.0 * res_lon
    pad_lat = 5.0 * res_lat

    min_lon, max_lon = float(np.min(lons)) - pad_lon, float(np.max(lons)) + pad_lon
    min_lat, max_lat = float(np.min(lats)) - pad_lat, float(np.max(lats)) + pad_lat

    x_grid = np.arange(min_lon, max_lon + res_lon, res_lon)
    y_grid = np.arange(min_lat, max_lat + res_lat, res_lat)

    # Bound grid size to avoid performance bottlenecks
    if len(x_grid) > 150:
        x_grid = np.linspace(min_lon, max_lon, 150)
        res_lon = x_grid[1] - x_grid[0]
    if len(y_grid) > 150:
        y_grid = np.linspace(min_lat, max_lat, 150)
        res_lat = y_grid[1] - y_grid[0]

    gx, gy = np.meshgrid(x_grid, y_grid)
    grid_coords = np.vstack([gx.ravel(), gy.ravel()])
    density = kde(grid_coords).reshape(gx.shape)

    # Sort grid cells descending by density to compute highest-density region thresholds
    flat_d = density.ravel()
    sort_idx = np.argsort(flat_d)[::-1]
    sorted_d = flat_d[sort_idx]
    cum_mass = np.cumsum(sorted_d) / np.sum(sorted_d)

    # Find density threshold containing 50% and 90% of mass
    idx_50 = int(np.searchsorted(cum_mass, 0.50))
    idx_90 = int(np.searchsorted(cum_mass, 0.90))

    thresh_50 = float(sorted_d[min(idx_50, len(sorted_d) - 1)])
    thresh_90 = float(sorted_d[min(idx_90, len(sorted_d) - 1)])

    # Affine transform for rasterio shapes
    # Row 0 is at y_grid[-1] (north)
    aff = affine.Affine(
        res_lon, 0.0, x_grid[0] - res_lon / 2.0,
        0.0, -res_lat, y_grid[-1] + res_lat / 2.0,
    )

    def extract_multipolygon(mask_2d: np.ndarray) -> MultiPolygon:
        # Flip vertically so row 0 is top (north)
        flipped_mask = mask_2d[::-1, :].astype(np.int16)
        shapes = rasterio.features.shapes(
            flipped_mask,
            mask=(flipped_mask == 1),
            transform=aff,
        )
        polys = []
        for g, v in shapes:
            if v == 1:
                p = shapely.geometry.shape(g)
                if not p.is_valid:
                    p = shapely.make_valid(p)
                if isinstance(p, Polygon) and not p.is_empty:
                    polys.append(p)
                elif isinstance(p, MultiPolygon):
                    polys.extend([sub for sub in p.geoms if not sub.is_empty])

        if not polys:
            return MultiPolygon()
        merged = shapely.unary_union(polys)
        if isinstance(merged, Polygon):
            return MultiPolygon([merged])
        elif isinstance(merged, MultiPolygon):
            return merged
        return MultiPolygon()

    p50 = extract_multipolygon(density >= thresh_50)
    p90 = extract_multipolygon(density >= thresh_90)

    # Ensure validity
    if not p50.is_valid:
        p50 = shapely.make_valid(p50)
    if not p90.is_valid:
        p90 = shapely.make_valid(p90)

    return {
        "horizon_h": horizon_h,
        "centroid": centroid,
        "p50": p50 if isinstance(p50, MultiPolygon) else MultiPolygon([p50]),
        "p90": p90 if isinstance(p90, MultiPolygon) else MultiPolygon([p90]),
    }


# ---------------------------------------------------------------------------
# 6. Serialization (Tracks URL & Storage)
# ---------------------------------------------------------------------------

def save_tracks(
    tracks: np.ndarray,
    forecast_id: Union[int, str],
    storage_dir: Optional[str] = None,
) -> str:
    """
    Save particle tracks array (500, 169, 2) as float32 .npy.
    If BLOB_READ_WRITE_TOKEN is set, attempts to upload to Vercel Blob.
    Otherwise saves locally and returns the file path/URL.
    """
    if storage_dir is None:
        storage_dir = os.path.join("data", "tracks")

    os.makedirs(storage_dir, exist_ok=True)
    filename = f"forecast_{forecast_id}_tracks.npy"
    local_path = os.path.join(storage_dir, filename)

    np.save(local_path, tracks.astype(np.float32))

    # Optional Vercel Blob upload if configured
    if BLOB_READ_WRITE_TOKEN:
        try:
            import requests
            blob_api_url = f"https://blob.vercel-storage.com/{filename}"
            with open(local_path, "rb") as f:
                resp = requests.put(
                    blob_api_url,
                    data=f,
                    headers={
                        "Authorization": f"Bearer {BLOB_READ_WRITE_TOKEN}",
                        "x-add-random-suffix": "false",
                    },
                    timeout=10.0,
                )
                if resp.status_code in (200, 201):
                    blob_url = resp.json().get("url")
                    if blob_url:
                        return blob_url
        except Exception as e:
            logger.warning(f"Vercel Blob upload failed ({e}). Using local file path.")

    return str(Path(local_path).resolve())


def load_tracks(tracks_url: str) -> np.ndarray:
    """Load particle tracks from a local path or URL."""
    if tracks_url.startswith("http://") or tracks_url.startswith("https://"):
        import requests
        import io
        resp = requests.get(tracks_url, timeout=10.0)
        resp.raise_for_status()
        return np.load(io.BytesIO(resp.content))

    # Remove file:// prefix if present
    path = tracks_url.replace("file://", "")
    return np.load(path)


# ---------------------------------------------------------------------------
# 7. High-Level Forecast Orchestration
# ---------------------------------------------------------------------------

def run_ensemble_forecast(
    patch_id: str,
    seeded_from: str = "observation",
    geometry: Optional[Any] = None,
    seed_obs_id: Optional[int] = None,
    prev_tracks: Optional[np.ndarray] = None,
    t0: Optional[datetime] = None,
    prev_t0: Optional[datetime] = None,
    forecast_id: Optional[Union[int, str]] = None,
    hours: int = FORECAST_HOURS,
    metocean: Optional[MetOceanField] = None,
    land_geom: Optional[Any] = None,
    storage_dir: Optional[str] = None,
    rng: Optional[np.random.Generator] = None,
    centroid: Optional[Tuple[float, float]] = None,
) -> Dict[str, Any]:
    """
    Run full 500-particle ensemble forecast:
    1. Seed particles from observation geometry or previous ensemble.
    2. Draw stochastic parameters (windage, leeway angle, current scale).
    3. Run RK4 integration over 168 hours with diffusion and land beaching.
    4. Compute 24h and 48h probability area KDE contours (p50 and p90).
    5. Save tracks .npy and format records for database tables.
    """
    if t0 is None:
        t0 = datetime.now(timezone.utc)
    if forecast_id is None:
        forecast_id = f"{patch_id}_{int(t0.timestamp())}"
    if rng is None:
        rng = np.random.default_rng()

    if geometry is None and centroid is not None:
        geometry = Point(centroid[0], centroid[1])

    # 1. Seeding
    particles_init = seed_particles(
        geometry=geometry,
        seeded_from=seeded_from,
        prev_tracks=prev_tracks,
        t0=t0,
        prev_t0=prev_t0,
        n_particles=ENSEMBLE_PARTICLES,
        rng=rng,
    )

    # 2. Parameters
    params = draw_particle_parameters(n_particles=ENSEMBLE_PARTICLES, rng=rng)

    # 3. Met-Ocean environment
    if metocean is None:
        min_lon, max_lon = float(particles_init[:, 0].min()), float(particles_init[:, 0].max())
        min_lat, max_lat = float(particles_init[:, 1].min()), float(particles_init[:, 1].max())
        metocean = fetch_metocean_forecast(
            min_lon=min_lon, min_lat=min_lat,
            max_lon=max_lon, max_lat=max_lat,
            t0=t0, hours=hours,
        )

    # 4. RK4 Integration
    tracks, beached_mask = integrate_rk4(
        particles_init=particles_init,
        metocean=metocean,
        params=params,
        hours=hours,
        land_geom=land_geom,
        rng=rng,
    )

    # 5. Probability Areas
    areas = []
    for h in PROBABILITY_HORIZONS_H:
        if h < tracks.shape[1]:
            area_h = compute_probability_areas(tracks, horizon_h=h)
            areas.append({
                "forecast_id": forecast_id,
                "horizon_h": h,
                "p50": area_h["p50"],
                "p90": area_h["p90"],
                "centroid": area_h["centroid"],
            })

    # 6. Save tracks
    tracks_url = save_tracks(tracks, forecast_id=forecast_id, storage_dir=storage_dir)

    # 7. Format database record for forecasts table
    forecast_record = {
        "forecast_id": forecast_id,
        "patch_id": patch_id,
        "seeded_from": seeded_from,
        "seed_obs_id": seed_obs_id,
        "issued_at": datetime.now(timezone.utc),
        "t0": t0,
        "params": {
            "n_particles": ENSEMBLE_PARTICLES,
            "hours": hours,
            "beached_count": int(np.sum(beached_mask)),
        },
        "tracks_url": tracks_url,
    }

    return {
        "forecast_record": forecast_record,
        "forecast": forecast_record,
        "forecast_areas": areas,
        "tracks": tracks,
        "beached_mask": beached_mask,
    }
