from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "systemd" / "factory.service"


def test_service_makes_factory_files_group_writable():
    assert "UMask=0007" in SERVICE.read_text()
