from unittest.mock import patch

from core import worker


def test_worker_invocation_uses_configured_internal_secret(monkeypatch):
    monkeypatch.setattr(
        worker, "WORKER_URL", "https://worker.example.test/api/jobs/process_scene"
    )
    monkeypatch.setattr(worker, "CRON_SECRET", "worker-secret")
    with patch("core.worker.urlopen") as urlopen:
        response = urlopen.return_value.__enter__.return_value
        response.status = 202

        result = worker.trigger_process_scene()

        assert result["status"] == "triggered"
        request = urlopen.call_args.args[0]
        assert request.get_header("Authorization") == "Bearer worker-secret"
