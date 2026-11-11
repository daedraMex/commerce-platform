from pathlib import Path

import yaml

COMPOSE_FILE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def load_services():
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]


def test_compose_runs_a_celery_worker():
    worker = load_services()["worker"]

    assert "celery" in worker["command"]
    assert "worker" in worker["command"]
    assert "beat" not in worker["command"]


def test_compose_has_no_beat_process():
    services = load_services()

    assert "beat" not in services
    assert all("beat" not in str(service.get("command", "")) for service in services.values())
