# Night factory — runbook

The night factory is an unattended runner on a dedicated Pop!_OS machine. It
implements tickets marked agent-ready overnight and opens draft pull requests.
The decisions behind it are in `docs/adr/0025-night-factory-unattended-agent-runner.md`.

- Code lives in `tools/factory/` (a small Python package run with `uv`).
- It is governed by the factory-only OpenCode config
  `tools/factory/opencode.factory.json`, loaded via the `OPENCODE_CONFIG`
  environment variable, so the repo's own `opencode.json` is untouched.
- It never pushes to `main`, never force-pushes, never merges. A human signs
  twice: marking a ticket agent-ready, then approving and merging the PR.

## Machine layout

Everything lives under the `factory` user's home (`~/factory`):

```
~/factory/
├── repo/          # a clone of daedraMex/commerce-platform (the factory's git source)
├── worktrees/     # one git worktree per ticket, cleaned after 14 days
├── logs/          # one log file per ticket run, cleaned after 14 days
└── secrets.env    # chmod 600, see below
```

## One-time machine setup

Run these once, as the admin user unless a step says `factory`.

1. **Install Pop!_OS on the dedicated machine.** Join it to the Tailscale
   tailnet so you can reach it over the private network.

2. **PostgreSQL 16 and Redis 7 as admin-managed services.** The factory runs
   the test suite, which needs both. Install them system-wide and make them
   reachable from the `factory` user (a dedicated test database and a local
   socket or a password the test settings can use). These are *not* production
   databases; they hold nothing but test data.

3. **Create the `factory` user.** No sudo, not in the `docker` group:
   ```bash
   sudo useradd --create-home --shell /bin/bash factory
   ```

4. **Install the toolchain as `factory`:** `uv` (Python 3.12), Node.js, and
   OpenCode. Pin OpenCode to `1.19.5` (the factory config uses the V1
   permission syntax; newer `opencode2` uses a different schema):
   ```bash
   curl -fsSL https://astral.sh/uv/install.sh | sh   # gives ~/.local/bin/uv
   # then install node, and opencode 1.19.5
   ```

5. **Clone the repo and sync the factory package** as `factory`:
   ```bash
   git clone https://github.com/daedraMex/commerce-platform.git ~/factory/repo
   cd ~/factory/repo/tools/factory
   uv sync
   ```

6. **Sign in as the machine account.** Create a GitHub **machine account**
   that is a collaborator on `daedraMex/commerce-platform` only. Give it a
   fine-grained token scoped to this repo only: `contents` (read/write),
   `pull requests` (read/write), `issues` (read/write), `metadata` (read).
   Authenticate `gh` on the `factory` user with that token:
   ```bash
   gh auth login   # use the machine account's fine-grained token
   ```

7. **Give OpenCode the model provider key** as `factory` (`opencode auth
   login`), and set a **spending cap** on the provider account. The machine
   must never receive the production, R2, payment or per-store integration
   credentials, and never the real `.env`.

8. **Create the secrets file** `~/factory/secrets.env`, `chmod 600`, with the
   settings the factory reads from the environment:
   ```bash
   FACTORY_MODEL=deepseek/deepseek-flash        # the cheap default model
   FACTORY_STRONG_MODEL=deepseek/deepseek-v4-pro # for strong-model tickets
   FACTORY_TELEGRAM_BOT_TOKEN=123456:ABC...     # from @BotFather
   FACTORY_TELEGRAM_CHAT_ID=123456789           # the one fixed chat id
   # optional overrides:
   # FACTORY_MAX_TICKETS=1
   # FACTORY_REPO=daedraMex/commerce-platform
   ```
   All `FACTORY_*` settings are listed in `tools/factory/src/factory/config.py`.

9. **Create the Telegram bot** with [@BotFather](https://t.me/BotFather),
   take its token into `FACTORY_TELEGRAM_BOT_TOKEN`, and find the one chat id
   the bot sends to (message the bot, then read the chat id from the
   `getUpdates` response, then disable updates — the bot only sends, it never
   polls or accepts commands).

10. **Install the systemd user units** as `factory`:
    ```bash
    mkdir -p ~/.config/systemd/user
    cp ~/factory/repo/tools/factory/systemd/factory.service ~/.config/systemd/user/
    cp ~/factory/repo/tools/factory/systemd/factory.timer  ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now factory.timer
    loginctl enable-linger factory   # keep the timer alive when nobody is logged in
    ```

11. **Protect `main`.** On GitHub: require a pull request before merging,
    require 1 approval, require the "Backend" and "Ticket link" checks, and
    disallow bypassing them.

## How tickets become agent-ready

- When `/to-tickets` creates a ticket it is marked **HITL** (human-in-the-loop)
  or **AFK** (away-from-keyboard). Only **AFK** tickets may later get the
  `ready-for-agent` triage label.
- A ticket is **agent-ready** when it has `ready-for-agent`, all its blocking
  edges are closed, it has no open PR, and it is not labeled `needs-decision`.
- Add `strong-model` to a ticket that touches security, money, migrations or
  otherwise tricky logic; it runs with `FACTORY_STRONG_MODEL` instead of the
  default. The builder model is never the reviewer of its own work.
- Migrations and changes touching money, security or customer data still get a
  human review before merging (unchanged AGENTS.md safety rules).
- `FACTORY_MAX_TICKETS` (default 1) is how many independent tickets one run
  takes, oldest first, each on its own branch. Raise it only when a night has
  room for more than one independent ticket; the run still stops at the first
  failure.

## Reading logs and decisions

- Each run writes `~/factory/logs/<ticket>.log`. Read the tail of the log to
  see what the agent did and why it failed.
- The agent keeps a running decision log in `DECISIONS.md` at the worktree
  root (git-ignored, never committed). It holds every choice, the rejected
  alternative, and why. If the agent could not decide safely it writes the open
  question as the first line, starting with `OPEN QUESTION:`.
- Worktrees and logs older than 14 days are deleted at the start of each run.

## Answering a `needs-decision` ticket

A stuck ticket gets a comment (open question + decisions so far + last log
lines) and the `needs-decision` label. To unblock it:

1. Open the issue and read the comment.
2. Answer the open question (or edit the ticket).
3. Remove `needs-decision`. The next run picks it up again if it is still
   `ready-for-agent`.

## Run once by hand

As `factory`:
```bash
cd ~/factory/repo/tools/factory
set -a; source ~/factory/secrets.env; set +a
uv run factory
```

## Stopping it

```bash
systemctl --user stop factory.timer   # stop the schedule
systemctl --user stop factory.service # stop a run in progress
```

To see when the next run is scheduled:
```bash
systemctl --user list-timers factory.timer
```
