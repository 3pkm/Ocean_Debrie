CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS aoi (
    aoi_id serial PRIMARY KEY,
    name text NOT NULL,
    geom geometry(Polygon, 4326) NOT NULL,
    active boolean DEFAULT true,
    last_scene_time timestamptz
);

CREATE TABLE IF NOT EXISTS scenes (
    scene_id text PRIMARY KEY,
    aoi_id int REFERENCES aoi,
    sensing_time timestamptz,
    source text,
    cloud_frac real,
    status text DEFAULT 'queued',
    error text,
    processed_at timestamptz
);

CREATE TABLE IF NOT EXISTS patches (
    patch_id text PRIMARY KEY,
    parent_id text REFERENCES patches,
    aoi_id int REFERENCES aoi,
    status text NOT NULL CHECK (
        status IN ('active', 'occluded', 'lost', 'split', 'merged', 'stranded', 'expired')
    ),
    first_seen timestamptz,
    last_seen timestamptz,
    last_obs_id bigint,
    clear_evidence real DEFAULT 0
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id bigserial PRIMARY KEY,
    patch_id text REFERENCES patches,
    scene_id text REFERENCES scenes,
    geom geometry(Polygon, 4326),
    centroid geometry(Point, 4326),
    area_m2 real,
    confidence real,
    mean_fdi real,
    cloud_overlap real
);

CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id bigserial PRIMARY KEY,
    patch_id text REFERENCES patches,
    seeded_from text CHECK (seeded_from IN ('observation', 'ensemble')),
    seed_obs_id bigint,
    issued_at timestamptz,
    t0 timestamptz,
    params jsonb,
    tracks_url text
);

CREATE TABLE IF NOT EXISTS forecast_areas (
    forecast_id bigint REFERENCES forecasts,
    horizon_h int,
    p50 geometry(MultiPolygon, 4326),
    p90 geometry(MultiPolygon, 4326),
    centroid geometry(Point, 4326),
    PRIMARY KEY (forecast_id, horizon_h)
);

CREATE TABLE IF NOT EXISTS verifications (
    id bigserial PRIMARY KEY,
    patch_id text,
    forecast_id bigint,
    obs_id bigint,
    lead_h real,
    error_km real,
    in_p50 boolean,
    in_p90 boolean,
    persistence_error_km real,
    currents_only_error_km real,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS zones (
    zone_id serial PRIMARY KEY,
    name text,
    geom geometry(Polygon, 4326) NOT NULL,
    threshold_advisory real DEFAULT 0.20,
    threshold_warning real DEFAULT 0.50,
    channels jsonb NOT NULL,
    active boolean DEFAULT true,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS risk_evals (
    id bigserial PRIMARY KEY,
    zone_id int REFERENCES zones,
    patch_id text,
    forecast_id bigint,
    p_reach real,
    eta_p10 timestamptz,
    eta_p90 timestamptz,
    tier text,
    evaluated_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id bigserial PRIMARY KEY,
    dedupe_key text UNIQUE,
    zone_id int,
    patch_id text,
    scene_id text,
    tier text,
    p_reach real,
    eta_start timestamptz,
    eta_end timestamptz,
    payload jsonb,
    channel text,
    status text DEFAULT 'pending',
    attempts int DEFAULT 0,
    next_attempt_at timestamptz,
    sent_at timestamptz,
    last_error text,
    delivered_channels jsonb NOT NULL DEFAULT '[]'::jsonb
);

ALTER TABLE alerts
    ADD COLUMN IF NOT EXISTS delivered_channels jsonb NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS jobs (
    job_id bigserial PRIMARY KEY,
    kind text,
    scene_id text,
    status text DEFAULT 'queued',
    attempts int DEFAULT 0,
    locked_at timestamptz,
    created_at timestamptz DEFAULT now(),
    error text
);

CREATE TABLE IF NOT EXISTS events (
    id bigserial PRIMARY KEY,
    patch_id text,
    event text,
    at timestamptz DEFAULT now(),
    detail jsonb
);

CREATE INDEX IF NOT EXISTS scenes_aoi_sensing_time_idx
    ON scenes (aoi_id, sensing_time DESC);
CREATE INDEX IF NOT EXISTS scenes_status_idx
    ON scenes (status);
CREATE INDEX IF NOT EXISTS patches_aoi_status_idx
    ON patches (aoi_id, status);
CREATE INDEX IF NOT EXISTS observations_patch_scene_idx
    ON observations (patch_id, scene_id);
CREATE INDEX IF NOT EXISTS observations_geom_gix
    ON observations USING gist (geom);
CREATE INDEX IF NOT EXISTS forecasts_patch_issued_at_idx
    ON forecasts (patch_id, issued_at DESC);
CREATE INDEX IF NOT EXISTS forecast_areas_p50_gix
    ON forecast_areas USING gist (p50);
CREATE INDEX IF NOT EXISTS forecast_areas_p90_gix
    ON forecast_areas USING gist (p90);
CREATE INDEX IF NOT EXISTS verifications_patch_created_at_idx
    ON verifications (patch_id, created_at DESC);
CREATE INDEX IF NOT EXISTS zones_active_idx
    ON zones (active);
CREATE INDEX IF NOT EXISTS zones_geom_gix
    ON zones USING gist (geom);
CREATE INDEX IF NOT EXISTS risk_evals_zone_patch_evaluated_at_idx
    ON risk_evals (zone_id, patch_id, evaluated_at DESC);
CREATE INDEX IF NOT EXISTS alerts_pending_retry_idx
    ON alerts (next_attempt_at)
    WHERE status IN ('pending', 'failed');
CREATE INDEX IF NOT EXISTS jobs_status_created_at_idx
    ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS events_patch_at_idx
    ON events (patch_id, at DESC);
