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

## Prerequisites

- **git >= 2.46.** Pop!_OS 24.04 ships git 2.43, whose `safe.directory` does
  not support the `/srv/factory/worktrees/*` glob. Without the upgrade the glob
  silently does not match and git refuses a factory-owned worktree for
  `factory-agent` with "dubious ownership". Install the newer git from the
  git-core PPA, then confirm the version:
  ```bash
  sudo add-apt-repository ppa:git-core/ppa && sudo apt update && sudo apt install -y git
  git --version   # must be >= 2.46
  ```
  The factory also aborts at startup when it finds anything older.
- Python 3.12 (via uv), Node.js and OpenCode 1.19.5, installed in step 4.

## Machine layout

The main clone and the worktrees live under `/srv/factory`, outside
`/home/factory` (which stays `700` so its secrets are out of the agent's reach):

```
/srv/factory/           # factory:factory
├── repo/               # clone of daedraMex/commerce-platform (the factory's git source)
└── worktrees/          # factory:factory-work, mode 2770; one worktree per ticket,
                        # flat dir names: branch nf/46-slug -> nf-46-slug, so the
                        # sudoers check-script glob matches; cleaned after 14 days

/home/factory/          # factory:factory, mode 700
├── logs/               # one log file per ticket run, cleaned after 14 days
├── secrets.env         # chmod 600, see below
└── xolo-bot.pem        # chmod 600, see below
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

3. **Create two users and a shared worktree group.** The `factory` user runs the
   factory; the unprivileged `factory-agent` user is what OpenCode actually runs
   as, so the model can only reach its own worktree. Both are members of the
   dedicated `factory-work` group; `factory-agent` is **not** in the `factory`
   group:
    ```bash
    sudo useradd --create-home --shell /bin/bash factory
    sudo useradd --create-home --shell /bin/bash factory-agent
    sudo groupadd factory-work
    sudo usermod -a -G factory-work factory
    sudo usermod -a -G factory-work factory-agent
    ```

    Let `factory` act *as* `factory-agent` (a downgrade, never an upgrade), so
    it can launch OpenCode as the sandbox user, run the isolation check and run
    `check.sh`. The sudo calls are always non-interactive (`-n`) so a missing
    rule fails fast instead of waiting for a password, use full command paths,
    and name every variable in `--preserve-env` because sudo's `env_reset`
    would otherwise drop it. The `SETENV` tag is what allows that:
    ```
    # /etc/sudoers.d/factory-agent
    Defaults>factory-agent umask=0007
    Defaults>factory-agent umask_override
    factory ALL=(factory-agent) NOPASSWD:SETENV: /usr/bin/opencode, /usr/bin/cat, /usr/bin/test, /srv/factory/worktrees/*/backend/scripts/check.sh
    ```

    The two `Defaults>factory-agent` lines make every file `factory-agent`
    creates group-writable, so `factory` can commit and clean up the worktree;
    `factory.service` sets `UMask=0007` for the same reason in the other
    direction. The setgid bit on `/srv/factory/worktrees` gives both users the
    shared `factory-work` group. Git also refuses to operate on a worktree owned
    by another user, so trust the worktree glob for `factory-agent` (as admin):
    ```bash
    sudo -u factory-agent -H git config --global --add safe.directory '/srv/factory/worktrees/*'
    ```

    Create the machine layout. `/home/factory` stays `700`; only the worktrees
    are group-writable, so `factory-agent` can edit its own worktree while the
    secrets stay out of reach:
    ```bash
    sudo install -d -m 755 -o factory -g factory /srv/factory
    sudo install -d -m 2770 -o factory -g factory-work /srv/factory/worktrees
    sudo chmod 700 /home/factory
    ```

    The secrets file, the private key and the SSH deploy key
    (`~/.ssh/commerce_deploy`) remain owned by `factory` (mode `600`), so
    `factory-agent` cannot read them even via bash. The factory verifies this on
    every startup.

    Smoke-test the cross-user setup on the real machine by hand once (as admin),
    using a throwaway worktree whose flat name matches the sudoers glob:
    ```bash
    # 0. create a throwaway worktree and branch
    sudo -u factory git -C /srv/factory/repo worktree add \
      -b smoke-worktree /srv/factory/worktrees/smoke-worktree origin/main

    # 1. factory-agent creates a group-writable file
    sudo -u factory-agent touch /srv/factory/worktrees/smoke-worktree/smoke
    stat -c '%A %U:%G' /srv/factory/worktrees/smoke-worktree/smoke
    # expect: -rw-rw---- factory-agent factory-work
    sudo -u factory rm /srv/factory/worktrees/smoke-worktree/smoke

    # 2. the agent cannot write where the factory must stay in control
    sudo -u factory-agent test -w /srv/factory/repo; echo "agent write rc=$? (expect 1)"
    sudo -u factory-agent test -w /srv/factory/repo/.git/hooks; echo "agent hooks rc=$? (expect 1)"

    # 3. git accepts the factory-owned worktree as factory-agent (no "dubious ownership")
    sudo -u factory-agent git -C /srv/factory/worktrees/smoke-worktree status

    # 4. the sudoers rule allows check.sh without a password
    sudo -u factory sudo -n -u factory-agent -- \
      /srv/factory/worktrees/smoke-worktree/backend/scripts/check.sh
    # any result is fine except "sudo: a password is required"

    # 5. remove the throwaway worktree and branch
    sudo -u factory git -C /srv/factory/repo worktree remove --force \
      /srv/factory/worktrees/smoke-worktree
    sudo -u factory git -C /srv/factory/repo branch -D smoke-worktree
    ```

4. **Install the toolchain.** As `factory`, install `uv` (Python 3.12) and
   Node.js. Install OpenCode system-wide at `/usr/bin/opencode` (as admin),
   because the sudoers rule allows exactly that path. Pin OpenCode to `1.19.5`
   (the factory config uses the V1 permission syntax; newer `opencode2` uses a
   different schema):
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
    # then install node
    sudo install -m 755 opencode /usr/bin/opencode     # OpenCode 1.19.5
    ```

5. **Set up the read-only deploy key and clone** as `factory`. Fetching uses
   the read-only deploy key over SSH; pushes use HTTPS with the minted xolo-bot
   token:
    ```bash
    ssh-keygen -t ed25519 -N '' -C commerce-deploy -f ~/.ssh/commerce_deploy
    chmod 600 ~/.ssh/commerce_deploy
    # add ~/.ssh/commerce_deploy.pub to the repo's Deploy keys (read-only)
    cat >> ~/.ssh/config <<'EOF'
    Host github-commerce
      HostName github.com
      User git
      IdentityFile ~/.ssh/commerce_deploy
      IdentitiesOnly yes
    EOF
    chmod 600 ~/.ssh/config
    git clone git@github-commerce:daedraMex/commerce-platform.git /srv/factory/repo
    cd /srv/factory/repo
    git remote set-url --push origin https://github.com/daedraMex/commerce-platform.git
    cd tools/factory
    uv sync
    ```

6. **Create the `xolo-bot` GitHub App and install it on the repo only.** The
   factory does **not** store any `gh` auth and does **not** set a global git
   credential helper (a global helper would leak into the OpenCode subprocess).
   Instead:
   - Register a GitHub App (`xolo-bot`) in the machine account's org/personal
     settings, give it `contents` (read/write), `pull requests` (read/write)
     and `issues` (read/write), and install it on `daedraMex/commerce-platform`
     only. Note its App ID and Installation ID, and download its private key.
   - Save the private key as a file the `factory` user owns, `chmod 600`:
     ```bash
     install -m 600 xolo-bot.pem /home/factory/xolo-bot.pem
     ```
   - The factory mints a short-lived installation token on demand: one for the
     run's `gh` read calls (`list_tickets` and its blocker/PR lookups) and a
     fresh one inside the success and stuck paths. Each token is passed only to
     the subprocesses that need it; it is never stored and never reaches the
     OpenCode subprocess.

7. **Give OpenCode the model provider key.** Set a **spending cap** on the
   provider account. The key reaches the agent through the environment
   allowlist (see `FACTORY_PROVIDER_ENV_VARS` below), not through `opencode
   auth login`. The machine must never receive the production, R2, payment or
   per-store integration credentials, and never the real `.env`.

8. **Create the secrets file** `~/factory/secrets.env`, `chmod 600`, with the
   settings the factory reads from the environment:
    ```bash
    FACTORY_MODEL=deepseek/deepseek-flash        # the cheap default model
    FACTORY_STRONG_MODEL=deepseek/deepseek-v4-pro # for strong-model tickets
    FACTORY_TELEGRAM_BOT_TOKEN=123456:ABC...     # from @BotFather
    FACTORY_TELEGRAM_CHAT_ID=123456789           # the one fixed chat id
    XOLO_BOT_APP_ID=123456                       # the xolo-bot App ID
    XOLO_BOT_PRIVATE_KEY=$HOME/factory/xolo-bot.pem   # path to the private key file
    XOLO_BOT_INSTALLATION_ID=987654              # the installation on this repo
    # agent isolation + env allowlist:
    FACTORY_AGENT_USER=factory-agent
    FACTORY_AGENT_HOME=/home/factory-agent
    FACTORY_PROVIDER_ENV_VARS=DEEPSEEK_API_KEY   # model key(s) the agent may see
    FACTORY_HOST=factory@factory-host            # ssh target for the stuck handoff
    # optional overrides:
    # FACTORY_MAX_TICKETS=1
    # FACTORY_ATTEMPTS=5              # max agent steps per ticket
    # FACTORY_TIME_LIMIT_MINUTES=120  # max wall-clock per ticket
    # FACTORY_REPO=daedraMex/commerce-platform
    # FACTORY_REPO_DIR=/srv/factory/repo
    # FACTORY_WORKTREES_DIR=/srv/factory/worktrees
    # FACTORY_LOGS_DIR=/home/factory/logs
    # FACTORY_DEPLOY_KEY=/home/factory/.ssh/commerce_deploy
    ```
    All settings are listed in `tools/factory/src/factory/config.py`. The
    GitHub App private key lives in its own file because systemd's
    `EnvironmentFile` cannot hold a multiline PEM.

    `fetch_main` runs `git fetch origin main`, so it uses the SSH fetch URL and
    the read-only deploy key. The `gh` read calls (`list_tickets` and its
    blocker/PR lookups) use the GitHub API, not the git remote, and receive a
    fresh xolo-bot installation token from the token provider. No `gh auth`
    login and no global git credential helper are needed.

9. **Create the Telegram bot** with [@BotFather](https://t.me/BotFather),
   take its token into `FACTORY_TELEGRAM_BOT_TOKEN`, and find the one chat id
   the bot sends to (message the bot, then read the chat id from the
   `getUpdates` response, then disable updates — the bot only sends, it never
   polls or accepts commands).

10. **Install the systemd user units** as `factory`:
    ```bash
    mkdir -p ~/.config/systemd/user
    cp /srv/factory/repo/tools/factory/systemd/factory.service ~/.config/systemd/user/
    cp /srv/factory/repo/tools/factory/systemd/factory.timer  ~/.config/systemd/user/
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

## Hardening

- **Isolation.** OpenCode runs as `factory-agent`; on every startup the factory
  runs a positive control (that user must be able to `cat /etc/hostname`) and
  then proves it cannot read the GitHub App private key, `secrets.env` or
  `~/.ssh/commerce_deploy` (via `sudo -n -u factory-agent -- /usr/bin/cat -n
  <path>`). It also proves `factory-agent` cannot write to `/srv/factory`,
  `/srv/factory/repo` or `repo/.git/hooks` (via `/usr/bin/test -w`). Any result
  other than a clean "permission denied" or "not writable" aborts the run, so a
  broken sudo rule fails closed.
- **Env allowlist.** The factory launches `/usr/bin/opencode` as
  `sudo -n --preserve-env=<explicit list> -u factory-agent -- /usr/bin/opencode
  ...` with an explicit environment — `PATH`, `HOME` (the agent's home), `LANG`,
  `DATABASE_URL`, the model provider vars, and `OPENCODE_CONFIG` — nothing else.
  The check runner gets the same downgrade with only `PATH`, `HOME`, `LANG` and
  `DATABASE_URL`: no provider key, no GitHub token, no secrets.
- **Per-ticket budget.** Each ticket has a step budget (`FACTORY_ATTEMPTS`) and
  a time budget (`FACTORY_TIME_LIMIT_MINUTES`). Exceeding either stops the
  ticket as stuck and notifies Telegram.
- **Fix loop.** Before pushing, the factory runs `./scripts/check.sh` in the
  worktree **as `factory-agent`**, with only the base env allowlist; on failure
  it feeds a truncated tail of the output back to the agent and retries, up to
  the step budget.
- **Protected paths.** Before pushing, the factory inspects the diff. If it
  touches `.github/`, `tools/factory/`, `backend/scripts/`, `AGENTS.md`,
  `CLAUDE.md`, `opencode*.json`, `.opencode/` or `.pre-commit-config.yaml`, the
  ticket goes to `_stuck` with `protected path changed`; nothing is pushed and
  no PR is opened.
- **Stuck handoff.** A stuck ticket keeps its worktree; the Telegram message
  includes the `ssh` + `cd` command to enter it.

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
cd /srv/factory/repo/tools/factory
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
