"""
Core configuration and tuning parameters for Multispectral Ocean Debris Segmentation Engine.
All tunable defaults are centralized here as specified in plan.md.
"""

import os
from dataclasses import dataclass
from typing import Dict, Any

# Automatically load .env file if present in project root
_env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(_env_file):
    try:
        with open(_env_file, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k, _v = _k.strip(), _v.strip().strip('"').strip("'")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

# Environment variables
DATABASE_URL = os.getenv("DATABASE_URL", "")
DATABASE_URL_UNPOOLED = os.getenv("DATABASE_URL_UNPOOLED", "")
BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN", "")
MODEL_BLOB_URL = os.getenv("MODEL_BLOB_URL", "")

INGEST_SECRET = os.getenv("INGEST_SECRET", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")
ZONE_API_KEY = os.getenv("ZONE_API_KEY", "")

CDSE_USER = os.getenv("CDSE_USER", "")
CDSE_PASSWORD = os.getenv("CDSE_PASSWORD", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
EMAIL_API_KEY = os.getenv("EMAIL_API_KEY", "")
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "resend")
EMAIL_FROM = os.getenv("EMAIL_FROM", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SIGNING_KEY = os.getenv("WEBHOOK_SIGNING_KEY", "")
WORKER_URL = os.getenv("WORKER_URL", "")

# 9.1 Preprocessing & Inference
TILE_SIZE = 256
MAX_AOI_SIZE_KM = 30.0
CLOUD_DILATION_METERS = 400.0
DEBRIS_PROB_THRESHOLD = float(os.getenv("DEBRIS_PROB_THRESHOLD", "0.50"))

# Training Normalization Statistics (MARIDA mean & std per 14 channels)
# Channels: B1, B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12, FDI, NDVI, NDWI
NORM_MEANS = [0.10] * 14
NORM_STDS = [0.05] * 14

# 9.2 Patch Tracking & Splits
TRACKING_GATE_PERCENTILE = 90.0
TRACKING_DENSITY_FLOOR = 1e-6
TRACKING_EPSILON = 1e-6
TRACKING_WEIGHT_AREA = 1.0  # w_a
TRACKING_WEIGHT_FDI = 1.0  # w_s

SPLIT_MIN_AREA_RATIO = 0.5
SPLIT_MAX_AREA_RATIO = 1.5
SPLIT_MAX_DISTANCE_KM = 3.0

# 9.3 Cloud-Aware Status
VISIBILITY_CLEAR_THRESHOLD = 0.5  # V < 0.5 => occluded
CLEAR_EVIDENCE_THRESHOLD = 1.5  # clear_evidence >= 1.5 => lost
EXPIRY_DAYS = 21.0  # unobserved > 21 days => expired

# 9.5 Ensemble Forecast Parameters
ENSEMBLE_PARTICLES = 500
FORECAST_HOURS = 168  # 7 days
FORECAST_TIME_STEP_HOURS = 1.0

WINDAGE_MEAN = 0.02
WINDAGE_STD = 0.007
WINDAGE_MIN = 0.005
WINDAGE_MAX = 0.04

LEEWAY_ANGLE_MEAN_DEG = 0.0
LEEWAY_ANGLE_STD_DEG = 10.0

CURRENT_SCALE_MEAN = 1.0
CURRENT_SCALE_STD = 0.15

DIFFUSION_COEFF_K = 10.0  # m^2 / s

PROBABILITY_HORIZONS_H = [24, 48]
PROBABILITY_LEVELS = [0.50, 0.90]

# 9.6 Zone Risk & Alerting
ZONE_DEFAULT_ADVISORY = 0.20
ZONE_DEFAULT_WARNING = 0.50
ALERT_MIN_PROB_DELTA = 0.15
ALERT_WINDOW_P10 = 0.10
ALERT_WINDOW_P90 = 0.90
