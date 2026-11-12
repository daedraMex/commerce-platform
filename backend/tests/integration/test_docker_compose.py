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


def command_text(service):
    command = service.get("command", "")
    if isinstance(command, str):
        return command
    return "\n".join(str(part) for part in command)


def test_compose_has_no_beat_process():
    services = load_services()

    assert "beat" not in services
    assert all("beat" not in str(service.get("command", "")) for service in services.values())


def test_compose_runs_minio_with_pinned_release_images():
    services = load_services()

    minio = services["minio"]
    assert minio["image"].startswith("minio/minio:RELEASE.")
    assert "server /data" in command_text(minio)

    init = services["minio-init"]
    assert init["image"].startswith("minio/mc:RELEASE.")
    script = command_text(init)
    assert "mc mb" in script
    assert "anonymous set download" in script
    assert "anonymous set none" in script
