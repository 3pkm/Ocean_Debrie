import json
import unittest
from unittest.mock import patch

from core.api_reads import _patch_record, _zone_record, get_freshness
from core.api_writes import _validate_postgis_polygon, validate_polygon_geojson
from core.api_utils import ApiRequestError, geojson_value, parse_fraction


class ReadApiTests(unittest.TestCase):
    def test_patch_record_builds_latest_observation_contract(self):
        record = _patch_record(
            {
                "patch_id": "P-01",
                "parent_id": None,
                "aoi_id": 1,
                "status": "active",
                "first_seen": None,
                "last_seen": None,
                "clear_evidence": 0,
                "obs_id": 42,
                "scene_id": "S2_TEST",
                "centroid_geojson": '{"type":"Point","coordinates":[1,2]}',
                "geom_geojson": None,
                "area_m2": 10,
                "confidence": 0.9,
                "mean_fdi": 0.04,
                "cloud_overlap": 0.01,
            }
        )
        self.assertEqual(record["patch_id"], "P-01")
        self.assertEqual(record["latest_obs"]["obs_id"], 42)
        self.assertEqual(record["latest_obs"]["centroid"]["coordinates"], [1, 2])
        self.assertIsNone(record["latest_obs"]["geom"])

    def test_zone_record_does_not_expose_delivery_credentials(self):
        record = _zone_record(
            {
                "zone_id": 4,
                "name": "Harbour",
                "geom_geojson": '{"type":"Polygon","coordinates":[]}',
                "threshold_advisory": 0.2,
                "threshold_warning": 0.5,
                "channels": '{"webhook_secret":"private"}',
                "active": True,
                "created_at": None,
            }
        )
        self.assertEqual(record["geom"]["type"], "Polygon")
        self.assertNotIn("channels", record)

    def test_geojson_value_accepts_decoded_and_string_values(self):
        expected = {"type": "Point", "coordinates": [0, 0]}
        self.assertEqual(geojson_value(expected), expected)
        self.assertEqual(geojson_value(json.dumps(expected)), expected)

    def test_zone_polygon_validation_rejects_invalid_and_out_of_bounds(self):
        valid = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        }
        self.assertEqual(json.loads(validate_polygon_geojson(valid)), valid)
        unclosed = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [2, 2], [0, 2], [2, 0]]],
        }
        with self.assertRaisesRegex(ApiRequestError, "rings must be closed"):
            validate_polygon_geojson(unclosed)
        out_of_bounds = {
            "type": "Polygon",
            "coordinates": [[[181, 0], [182, 0], [182, 1], [181, 1], [181, 0]]],
        }
        with self.assertRaisesRegex(ApiRequestError, "WGS84 bounds"):
            validate_polygon_geojson(out_of_bounds)

    def test_postgis_geometry_validation_rejects_self_intersection(self):
        class Cursor:
            def execute(self, query, params):
                self.query = query
                self.params = params

            def fetchone(self):
                return {"valid": False}

        with self.assertRaisesRegex(ApiRequestError, "non-self-intersecting"):
            _validate_postgis_polygon(Cursor(), '{"type":"Polygon"}')

    def test_fraction_rejects_non_finite_values(self):
        with self.assertRaises(ApiRequestError):
            parse_fraction(float("nan"), "threshold")
        with self.assertRaises(ApiRequestError):
            parse_fraction(1.01, "threshold")

    @patch("core.api_reads.db_fetch_one")
    def test_freshness_reports_unavailable_feed_timestamps_as_null(self, fetch_one):
        fetch_one.return_value = {
            "last_scene_utc": None,
            "last_scene_age_hours": None,
            "last_risk_refresh_utc": None,
            "active_patches_count": 0,
            "occluded_patches_count": 0,
            "pending_alerts_count": 0,
        }
        result = get_freshness()
        self.assertIsNone(result["wind_forecast_updated_utc"])
        self.assertIsNone(result["currents_forecast_updated_utc"])
        self.assertEqual(result["active_patches_count"], 0)


if __name__ == "__main__":
    unittest.main()
