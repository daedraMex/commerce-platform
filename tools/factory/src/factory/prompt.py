"""Compose the prompt handed to the agent for one ticket."""

from __future__ import annotations

from .tickets import Ticket

_TOKENS = (
    "{{TICKET_NUMBER}}",
    "{{TICKET_TITLE}}",
    "{{TICKET_BODY}}",
    "{{MODEL}}",
    "{{MAX_ATTEMPTS}}",
    "{{BRANCH}}",
)


def compose_prompt(
    ticket: Ticket,
    *,
    model: str,
    branch: str,
    max_attempts: int,
    template: str,
) -> str:
    values = (
        str(ticket.number),
        ticket.title,
        ticket.body,
        model,
        str(max_attempts),
        branch,
    )
    prompt = template
    for token, value in zip(_TOKENS, values, strict=True):
        prompt = prompt.replace(token, value)
    return prompt
