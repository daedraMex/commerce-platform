from pathlib import Path

import yaml

CI_FILE = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"


def level2_steps():
    workflow = yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))
    return workflow["jobs"]["level2"]["steps"]


def step_scripts(steps):
    return [(step.get("name", ""), step.get("run", "")) for step in steps]


def test_level2_starts_minio_and_creates_both_buckets():
    scripts = step_scripts(level2_steps())

    minio_steps = [script for _, script in scripts if "minio/minio:RELEASE." in script]
    assert minio_steps, "the level-2 job must start a pinned MinIO image"

    mc_steps = [script for _, script in scripts if "minio/mc:RELEASE." in script]
    assert mc_steps, "the level-2 job must create the buckets with pinned mc"
    assert any("mc mb" in script for script in mc_steps)
    assert any("anonymous set download" in script for script in mc_steps)
    assert any("anonymous set none" in script for script in mc_steps)


def test_level2_masks_the_generated_minio_password_and_exports_r2_names():
    scripts = step_scripts(level2_steps())
    combined = "\n".join(script for _, script in scripts)

    assert "openssl rand" in combined
    assert "::add-mask::" in combined
    assert "R2_BUCKET_NAME=" in combined
    assert "R2_PRIVATE_BUCKET_NAME=" in combined
    assert "R2_ACCESS_KEY_ID=" in combined
    assert "R2_SECRET_ACCESS_KEY=" in combined
    assert "R2_ENDPOINT_URL=" in combined
