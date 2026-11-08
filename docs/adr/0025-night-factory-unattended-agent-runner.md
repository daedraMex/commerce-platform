---
status: accepted
---

# The night factory is an unattended runner on a dedicated machine, gated by two human signatures

A dedicated machine (Pop!_OS) runs an unattended "night factory" that, overnight, implements tickets marked agent-ready and opens draft pull requests. It runs as an unprivileged `factory` user (no sudo, not in the docker group); PostgreSQL and Redis for the tests run as services managed by the admin user. The machine never holds production, R2, payment or per-store integration credentials, and never the real `.env`. It holds only the model provider key (with a spending cap set in the provider account), the Telegram bot token and the credentials of the `xolo-bot` GitHub App (its private key and installation id). GitHub write access uses a fresh installation token minted on demand and passed only to the push and pull-request subprocesses, never stored and never exposed to the OpenCode subprocess, which runs with `GH_TOKEN`/`GITHUB_TOKEN` stripped and no global git credential helper or stored `gh` auth. A human signs twice: first by marking a ticket agent-ready (approving the plan), then by approving and merging the PR. The factory may only push the branches named in its tickets' delivery notes and open draft PRs with `Closes #<ticket>`; it never pushes to `main`, never force-pushes and never merges, and `main` is protected (pull request required, one approval, required checks "Backend" and "Ticket link", no bypass).

## Considered Options

- Run the agent on the operator's own machine: rejected, because it shares production credentials and the real `.env`, and nothing stops the model from reading them.
- A cloud CI runner that signs its own commits: rejected, because it holds broader credentials and removes the human signatures this decision requires.

## Consequences

- Ticket readiness uses the triage label `ready-for-agent`; every ticket is marked HITL or AFK when `/to-tickets` creates it, and only AFK tickets may get `ready-for-agent` (see the skills' triage labels).
- The model is chosen per ticket: a cheap default (`FACTORY_MODEL`) and a stronger model (`FACTORY_STRONG_MODEL`) for tickets labeled `strong-model`. The builder model is never the reviewer of its own work.
- Migrations and changes touching money, security or customer data still get a human review before merging, unchanged from AGENTS.md.
- The factory's own code lives in `tools/factory/`, run with uv, and its notifications go through a Telegram bot behind a replaceable Notifier port.
