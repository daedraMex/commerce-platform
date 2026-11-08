from factory.prompt import compose_prompt, read_command_body
from factory.tickets import Ticket

COMMAND = "Read .agents/skills/implement/SKILL.md and follow it.\n\n$ARGUMENTS"
OVERLAY = "Branch: {{BRANCH}} Model: {{MODEL}} Attempts: {{MAX_ATTEMPTS}}"


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
        max_attempts=5,
        command_template=COMMAND,
        overlay=OVERLAY,
    )
    assert "Read .agents/skills/implement/SKILL.md and follow it." in prompt
    assert "#3: Add thing" in prompt
    assert "Acceptance criteria here." in prompt
    assert "Branch: nf/3-add-thing" in prompt
    assert "Model: deepseek/deepseek-flash" in prompt
    assert "Attempts: 5" in prompt
    assert "$ARGUMENTS" not in prompt
    assert "{{" not in prompt
