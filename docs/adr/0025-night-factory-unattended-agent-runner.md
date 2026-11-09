---
status: accepted
---

# The night factory is an unattended runner on a dedicated machine, gated by two human signatures

A dedicated machine (Pop!_OS) runs an unattended "night factory" that, overnight, implements tickets marked agent-ready and opens draft pull requests. It runs as an unprivileged `factory` user (no sudo, not in the docker group); PostgreSQL and Redis for the tests run as services managed by the admin user. The machine never holds production, R2, payment or per-store integration credentials, and never the real `.env`. It holds only the model provider key (with a spending cap set in the provider account), the Telegram bot token and the credentials of the `xolo-bot` GitHub App (its private key and installation id). GitHub write access uses a fresh installation token minted on demand and passed only to the push and pull-request subprocesses, never stored. OpenCode runs as a separate unprivileged `factory-agent` user, verified on startup to be unable to read the private key, the secrets file or the SSH deploy key (`~/.ssh/commerce_deploy`), and to be unable to write the factory tree or the repo's git hooks, and receives an explicit environment allowlist (not the factory user's full environment); the model provider key lives in the agent's own OpenCode auth store so it never crosses the sudo boundary or reaches the journal. A human signs twice: first by marking a ticket agent-ready (approving the plan), then by approving and merging the PR. The factory may only push the branches named in its tickets' delivery notes and open draft PRs with `Closes #<ticket>`; it never pushes to `main`, never force-pushes and never merges, and `main` is protected (pull request required, one approval, required checks "Backend" and "Ticket link", no bypass).

## Considered Options

- Run the agent on the operator's own machine: rejected, because it shares production credentials and the real `.env`, and nothing stops the model from reading them.
- A cloud CI runner that signs its own commits: rejected, because it holds broader credentials and removes the human signatures this decision requires.

## Consequences

- Ticket readiness uses the triage label `ready-for-agent`; every ticket is marked HITL or AFK when `/to-tickets` creates it, and only AFK tickets may get `ready-for-agent` (see the skills' triage labels).
- The model is chosen per ticket: a cheap default (`FACTORY_MODEL`) and a stronger model (`FACTORY_STRONG_MODEL`) for tickets labeled `strong-model`. The builder model is never the reviewer of its own work.
- Each ticket runs under a step and time budget; the factory runs `check.sh` and feeds failures back to the agent up to the step budget, then hands the kept worktree to a human with an `ssh`/`cd` command.
- Migrations and changes touching money, security or customer data still get a human review before merging, unchanged from AGENTS.md.
- The factory's own code lives in `tools/factory/`, run with uv, and its notifications go through a Telegram bot behind a replaceable Notifier port.
- The runner commits each ticket as `xolo-bot[bot]` with an explicit `-c user.name`/`-c user.email` derived from `XOLO_BOT_USER_ID`, so a commit never depends on machine git identity; the agent leaves its changes uncommitted and the runner commits them.
- Stale and expired worktrees are deleted as `factory-agent` (the owner of files created with its own group or modes, such as pytest's cache and uv's venv), then pruned and their local branch removed; every cleanup step checks its exit code, so a failed cleanup is loud. Factory runs disable pytest's cache.
- Every run starts with a real-tool preflight: fetch `origin/main`, list tickets through the real `gh` path, create a throwaway worktree from fresh `origin/main`, run `check.sh` as the agent user with the real check environment, verify isolation, the git version, the bot commit identity and the sudoers no-logging rule, fail if the worktrees directory has entries git does not know about, prove the worktree cleanup removes an agent-owned `factory-agent:factory-agent` 0770 directory, then remove the worktree and branch even on failure. A failed step notifies Telegram (`preflight failed: <step>: <short error>`) and stops the run before it touches a ticket. `factory preflight` runs the same check by hand after any machine or factory change.
