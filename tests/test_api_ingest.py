import unittest
from unittest.mock import patch

from core.api_utils import is_authorized
from api.ingest.cdse import parse_scene_event
from api.jobs.fetch_latest import _latest_scene


class Headers(dict):
    def get(self, key, default=""):
        return super().get(key, default)


class IngestApiTests(unittest.TestCase):
    def test_cdse_scene_event_parsing_supports_stac_metadata(self):
        scene = parse_scene_event(
            {
                "id": "S2A_TEST",
                "properties": {
                    "datetime": "2026-10-21T10:30:00Z",
                    "eo:cloud_cover": 15,
                    "aoi_id": 2,
                },
            }
        )

        self.assertEqual(
            scene, ("S2A_TEST", 2, "2026-10-21T10:30:00Z", 0.15)
        )
        self.assertEqual(
            parse_scene_event(
                {"scene_id": "S2A_TEST", "properties": {"eo:cloud_cover": 1}}
            )[3],
            0.01,
        )

    def test_cdse_scene_event_rejects_missing_id_and_invalid_cloud_fraction(self):
        with self.assertRaisesRegex(ValueError, "scene_id"):
            parse_scene_event({"properties": {}})
        with self.assertRaisesRegex(ValueError, "between 0 and 1"):
            parse_scene_event({"scene_id": "S2A_TEST", "cloud_frac": 2})

    @patch("api.jobs.fetch_latest.get_db_cursor")
    def test_fetch_latest_selects_newest_registered_scene(self, get_cursor):
        cursor = get_cursor.return_value.__enter__.return_value
        expected = {
            "scene_id": "S2A_TEST",
            "aoi_id": 2,
            "sensing_time": "2026-10-21T10:30:00Z",
            "cloud_frac": 0.15,
        }
        cursor.fetchone.return_value = expected
        self.assertEqual(_latest_scene(), expected)
        self.assertIn("ORDER BY s.sensing_time DESC", cursor.execute.call_args.args[0])

    @patch("api.jobs.fetch_latest.get_db_cursor")
    def test_fetch_latest_returns_not_found_without_registered_scene(self, get_cursor):
        from core.api_utils import ApiRequestError

        cursor = get_cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        with self.assertRaisesRegex(ApiRequestError, "No scene is registered"):
            _latest_scene()

    def test_bearer_authorization_requires_a_configured_matching_secret(self):
        self.assertTrue(
            is_authorized(Headers({"Authorization": "Bearer ingest"}), "ingest")
        )
        self.assertFalse(
            is_authorized(Headers({"Authorization": "Bearer wrong"}), "ingest")
        )
        self.assertFalse(
            is_authorized(Headers({"Authorization": "Bearer anything"}), "")
        )
