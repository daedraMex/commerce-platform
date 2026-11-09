from pathlib import Path

import pytest

from factory.sudoers import (
    REQUIRED_LINE,
    SUDOERS_PATH,
    SudoersError,
    has_no_log_allowed,
    verify_sudoers_logging,
)


def test_required_line_and_path_are_the_documented_ones():
    assert SUDOERS_PATH == Path("/etc/sudoers.d/factory-agent")
    assert REQUIRED_LINE == "Defaults:factory !log_allowed"


def test_accepts_the_exact_line(tmp_path):
    path = tmp_path / "factory-agent"
    path.write_text(f"{REQUIRED_LINE}\n")

    verify_sudoers_logging(path)


def test_accepts_extra_spacing_and_comments(tmp_path):
    path = tmp_path / "factory-agent"
    path.write_text(
        "# managed by the night factory setup\n"
        "Defaults : factory    !log_allowed   # keep successful commands out of the journal\n"
        "Defaults>factory-agent umask=0007\n"
    )

    assert has_no_log_allowed(path.read_text())


def test_rejects_a_file_without_the_line(tmp_path):
    path = tmp_path / "factory-agent"
    path.write_text("Defaults>factory-agent umask=0007\n")

    with pytest.raises(SudoersError, match="must contain"):
        verify_sudoers_logging(path)


def test_rejects_a_commented_out_line(tmp_path):
    path = tmp_path / "factory-agent"
    path.write_text(f"# {REQUIRED_LINE}\n")

    with pytest.raises(SudoersError, match="must contain"):
        verify_sudoers_logging(path)


def test_missing_file_fails_closed_with_the_permission_hint(tmp_path):
    path = tmp_path / "factory-agent"

    with pytest.raises(SudoersError, match="root:factory"):
        verify_sudoers_logging(path)
