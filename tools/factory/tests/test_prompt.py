from pathlib import Path

from factory.prompt import compose_prompt, read_command_body
from factory.tickets import Ticket

COMMAND = "Read .agents/skills/implement/SKILL.md and follow it.\n\n$ARGUMENTS"
OVERLAY = "Branch: {{BRANCH}} Model: {{MODEL}}"
PROMPT_OVERLAY = Path(__file__).resolve().parents[1] / "prompt.md"


def test_read_command_body_strips_frontmatter():
    text = (
        "---\n"
        'description: "Implement a piece of work based on a spec or set of tickets."\n'
        "---\n\n"
        "Read .agents/skills/implement/SKILL.md and follow it.\n\n"
        "$ARGUMENTS\n"
    )
    body = read_command_body(text)
    assert "description" not in body
    assert "$ARGUMENTS" in body
    assert "Read .agents/skills/implement/SKILL.md" in body


def test_read_command_body_without_frontmatter_is_identity():
    assert read_command_body("hello\n") == "hello"


def test_compose_prompt_inlines_ticket_and_fills_overlay():
    ticket = Ticket(number=3, title="Add thing", body="Acceptance criteria here.")
    prompt = compose_prompt(
        ticket,
        model="deepseek/deepseek-flash",
        branch="nf/3-add-thing",
        command_template=COMMAND,
        overlay=OVERLAY,
    )
    assert "Read .agents/skills/implement/SKILL.md and follow it." in prompt
    assert "#3: Add thing" in prompt
    assert "Acceptance criteria here." in prompt
    assert "Branch: nf/3-add-thing" in prompt
    assert "Model: deepseek/deepseek-flash" in prompt
    assert "$ARGUMENTS" not in prompt
    assert "{{" not in prompt


def test_compose_prompt_appends_check_feedback():
    ticket = Ticket(number=3, title="Add thing", body="Body.")
    prompt = compose_prompt(
        ticket,
        model="m",
        branch="nf/3-add-thing",
        command_template=COMMAND,
        overlay=OVERLAY,
        feedback="1 failed, 9 passed",
    )
    assert "check.sh is still failing" in prompt
    assert "1 failed, 9 passed" in prompt


def test_compose_prompt_omits_feedback_when_empty():
    ticket = Ticket(number=3, title="Add thing", body="Body.")
    prompt = compose_prompt(
        ticket,
        model="m",
        branch="nf/3-add-thing",
        command_template=COMMAND,
        overlay=OVERLAY,
    )
    assert "check.sh is still failing" not in prompt


def test_overlay_tells_the_agent_not_to_commit():
    text = PROMPT_OVERLAY.read_text()

    assert "Do not commit." in text
    assert "Leave your changes in the worktree; the runner commits them." in text
    assert "Commit your work" not in text
    assert "before you commit" not in text
