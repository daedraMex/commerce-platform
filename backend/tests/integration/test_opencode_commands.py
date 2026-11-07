from pathlib import Path

COMMANDS_DIR = Path(__file__).resolve().parents[3] / ".opencode" / "commands"


def test_opencode_commands_read_the_skill_file():
    commands = sorted(COMMANDS_DIR.glob("*.md"))

    assert commands
    for path in commands:
        body = path.read_text(encoding="utf-8")
        name = path.stem
        assert f"Read .agents/skills/{name}/SKILL.md and follow it." in body
        assert "Call the Skill tool" not in body
