from pathlib import Path

import yaml

COMPOSE_FILE = Path(__file__).resolve().parents[3] / "docker-compose.yml"


def load_services():
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]


def command_text(service):
    command = service.get("command", "")
    if isinstance(command, str):
        return command
    return "\n".join(str(part) for part in command)


def test_compose_runs_a_celery_worker():
    worker = load_services()["worker"]

    assert "celery" in worker["command"]
    assert "worker" in worker["command"]
    assert "beat" not in worker["command"]


def test_compose_has_no_beat_process():
    services = load_services()

    assert "beat" not in services
    assert all("beat" not in str(service.get("command", "")) for service in services.values())


def test_compose_worker_uses_the_rustfs_buckets():
    worker = load_services()["worker"]

    assert "catalog-media" in worker["environment"]["R2_BUCKET_NAME"]
    assert "catalog-private" in worker["environment"]["R2_PRIVATE_BUCKET_NAME"]
    assert "rustfs" in worker["environment"]["R2_ENDPOINT_URL"]


def test_compose_runs_rustfs_with_pinned_images_and_aws_cli_setup():
    services = load_services()

    rustfs = services["rustfs"]
    assert rustfs["image"] == "rustfs/rustfs:1.0.5"
    assert rustfs["environment"]["RUSTFS_ACCESS_KEY"] == "${R2_ACCESS_KEY_ID:-rustfsadmin}"
    assert rustfs["environment"]["RUSTFS_SECRET_KEY"] == "${R2_SECRET_ACCESS_KEY:-rustfsadmin}"
    healthcheck = " ".join(rustfs["healthcheck"]["test"])
    assert "localhost:9000/health" in healthcheck

    init = services["storage-init"]
    assert init["image"] == "amazon/aws-cli:2.40.1"
    script = command_text(init)
    assert "s3api head-bucket" in script
    assert "s3api create-bucket" in script
    assert script.count("s3api put-bucket-policy") == 1
    assert "s3:GetObject" in script
    assert '"$$R2_BUCKET_NAME"' in script
    assert "mc " not in script


def test_compose_has_no_minio_images_left():
    content = COMPOSE_FILE.read_text(encoding="utf-8").lower()

    assert "minio" not in content
