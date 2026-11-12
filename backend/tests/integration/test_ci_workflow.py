from pathlib import Path

import yaml

CI_FILE = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def level2_steps():
    workflow = yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))
    return workflow["jobs"]["level2"]["steps"]


def step_scripts(steps):
    return [(step.get("name", ""), step.get("run", "")) for step in steps]


def test_level2_starts_rustfs_and_creates_both_buckets():
    scripts = step_scripts(level2_steps())
    combined = "\n".join(script for _, script in scripts)

    assert "rustfs/rustfs:1.0.5" in combined
    assert "amazon/aws-cli:2.40.1" in combined
    assert "s3api create-bucket" in combined
    assert combined.count("s3api put-bucket-policy") == 1
    assert "s3:GetObject" in combined
    assert "AccessDenied" in combined
    assert "public_status" in combined
    assert "private_status" in combined
    assert "mc " not in combined


def test_level2_masks_the_generated_rustfs_credentials_and_exports_r2_names():
    scripts = step_scripts(level2_steps())
    combined = "\n".join(script for _, script in scripts)

    assert "openssl rand" in combined
    assert "::add-mask::" in combined
    assert "RUSTFS_ACCESS_KEY=" in combined
    assert "RUSTFS_SECRET_KEY=" in combined
    assert "R2_BUCKET_NAME=" in combined
    assert "R2_PRIVATE_BUCKET_NAME=" in combined
    assert "R2_ACCESS_KEY_ID=" in combined
    assert "R2_SECRET_ACCESS_KEY=" in combined
    assert "R2_ENDPOINT_URL=" in combined


def test_level2_mentions_no_minio():
    content = CI_FILE.read_text(encoding="utf-8").lower()

    assert "minio" not in content
