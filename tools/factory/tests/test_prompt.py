from factory.prompt import compose_prompt
from factory.tickets import Ticket

TEMPLATE = (
    "Ticket {{TICKET_NUMBER}}: {{TICKET_TITLE}}\n"
    "Body: {{TICKET_BODY}}\n"
    "Model: {{MODEL}} Branch: {{BRANCH}} Attempts: {{MAX_ATTEMPTS}}\n"
)


def test_compose_prompt_fills_all_tokens():
    ticket = Ticket(number=3, title="Add thing", body="Acceptance criteria here.")
    prompt = compose_prompt(
        ticket,
        model="deepseek/deepseek-flash",
        branch="factory/3-add-thing",
        max_attempts=5,
        template=TEMPLATE,
    )
    assert "Ticket 3: Add thing" in prompt
    assert "Body: Acceptance criteria here." in prompt
    assert "Model: deepseek/deepseek-flash" in prompt
    assert "Branch: factory/3-add-thing" in prompt
    assert "Attempts: 5" in prompt
    assert "{{" not in prompt
