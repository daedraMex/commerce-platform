# Night factory — runbook

The night factory is an unattended runner on a dedicated Pop!_OS machine. It
runs every hour, around the clock, implements tickets marked agent-ready and
opens pull requests ready for review, and can address the owner's review
feedback on its own pull requests. All work stays within two caps: open pull
requests and daily ticket attempts. The decisions behind it are in
`docs/adr/0025-night-factory-unattended-agent-runner.md`.

- Code lives in `tools/factory/` (a small Python package run with `uv`).
- It is governed by the factory-only OpenCode config
  `tools/factory/opencode.factory.json`, read from `origin/main` and passed
  inline as `OPENCODE_CONFIG_CONTENT`, which outranks the repo's own
  `opencode.json` (left untouched for interactive use).
- It never pushes to `main`, never force-pushes, never approves and never merges
  directly. After opening a PR it marks it ready for review and enables
  auto-merge with the merge-commit method, so every factory PR needs the owner's
  GitHub approval before it can merge. If marking it ready or enabling
  auto-merge fails, the run still succeeds and the log says why; a PR that could
  not be marked ready stays a draft.
- A human signs twice: marking a ticket agent-ready, then approving the PR on
  GitHub; GitHub performs the auto-merge once the required checks pass.

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
- Python 3.12 (via uv), Node.js and OpenCode 1.19.5, installed in steps 4 and 5.

## Machine layout

The main clone and the worktrees live under `/srv/factory`, outside
`/home/factory` (which stays `700` so its secrets are out of the agent's reach):

```
/srv/factory/           # factory:factory
├── repo/               # clone of daedraMex/commerce-platform (the factory's git source)
└── worktrees/          # factory:factory-work, mode 2770; one worktree per ticket,
                        # flat dir names: branch nf/46-slug -> nf-46-slug, so the
                        # sudoers check-script and cleanup globs match; cleaned after 14 days

/home/factory/          # factory:factory, mode 700
├── logs/               # one log file per ticket run, cleaned after 14 days
├── state/              # mode 700; pause marker and the append-only ledgers
│   ├── attempts.log    # mode 600; started + outcome lines per attempt, never readable by factory-agent
│   ├── review-attempts.log  # mode 600; review ids already attempted, never readable by factory-agent
│   └── paused          # present only while the factory is paused
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
    each area's `check.sh`. The sudo calls are always non-interactive (`-n`) so a missing
    rule fails fast instead of waiting for a password, use full command paths,
    and name every variable in `--preserve-env` because sudo's `env_reset`
    would otherwise drop it. The `SETENV` tag is what allows that:
    ```
    Defaults:factory !log_allowed
    Defaults>factory-agent umask=0007
    Defaults>factory-agent umask_override
    factory ALL=(factory-agent) NOPASSWD:SETENV: /usr/bin/opencode, /usr/bin/cat, /usr/bin/test, /srv/factory/worktrees/*/backend/scripts/check.sh, /srv/factory/worktrees/*/web/console/scripts/check.sh, /usr/bin/rm -rf /srv/factory/worktrees/*, /usr/bin/pkill -KILL -u factory-agent
    ```

    The file lives at `/etc/sudoers.d/factory-agent`. Sudo's `*` does not
    cross `/`, so the two worktree globs match exactly one flat worktree
    directory. The code still validates every cleanup path itself: a sudoers
    glob is not a security boundary for `rm`.

    `Defaults:factory !log_allowed` stops sudo from writing the successful
    downgrade commands to the journal, including the environment named in
    `--preserve-env` and the prompt passed to OpenCode. Denied commands are
    still logged. This is why the provider key is never passed through sudo:
    the agent holds it itself (step 8).

    The rules live in `/etc/sudoers.d/factory-agent` and stay `root:root`; do
    not loosen its group or mode. The preflight runs `sudo -n -l` as `factory`
    (no password, because the rules are NOPASSWD) and checks the effective
    "Matching Defaults entries" for `!log_allowed`. If an older install left a
    `/etc/sudoers.d/factory` file behind, remove it so its stale rules cannot
    linger, then validate the sudoers files before relying on them:
    ```bash
    sudo rm -f /etc/sudoers.d/factory
    sudo visudo -c
    ```

    The two `Defaults>factory-agent` lines make files `factory-agent` creates
    through the agent normally group-writable, so `factory` can commit them;
    files with tighter modes (like `uv`'s 0755/0644 `.venv`) are removed by the
    agent-owned `rm -rf` cleanup instead. `factory.service` sets `UMask=0007`
    for the same reason in the other direction. The setgid bit on
    `/srv/factory/worktrees` gives both users the shared `factory-work` group. Git also refuses to operate on a worktree owned
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
    sudo install -d -m 700 -o factory -g factory /home/factory/state
    sudo chmod 700 /home/factory
    ```

    The secrets file, the private key and the SSH deploy key
    (`~/.ssh/commerce_deploy`) remain owned by `factory` (mode `600`), so
    `factory-agent` cannot read them even via bash. The state directory stays
    `700` and the attempts ledger `600` for the same reason: the agent can never
    read or rewrite the daily count. The factory verifies the secrets on every
    startup.

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

4. **Install the toolchain.** As `factory`, install `uv` (Python 3.12). Install
   OpenCode system-wide at `/usr/bin/opencode` (as admin), because the sudoers
   rule allows exactly that path. Pin OpenCode to `1.19.5` (the factory config
   uses the V1 permission syntax; newer `opencode2` uses a different schema).
   Node.js is installed system-wide in step 5:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
    sudo install -m 755 opencode /usr/bin/opencode     # OpenCode 1.19.5
    ```

5. **Install the console toolchain (admin user).** Install Node at the
   `.nvmrc` major (26) system-wide and enable pnpm through corepack for both
   users. The console check installs the workspace dependencies and the
   Playwright browser itself, but its system libraries need root once:
    ```bash
    curl -fsSL https://deb.nodesource.com/setup_26.x | sudo -E bash -
    sudo apt-get install -y nodejs
    sudo corepack enable
    sudo npx -y playwright@1.65.0 install-deps chromium   # version from pnpm-lock.yaml
    ```
    Confirm the toolchain as `factory-agent` (Node and the corepack-installed
    pnpm must be on its `PATH`), then dry-run the console check in a throwaway
    worktree whose flat name matches the sudoers glob:
    ```bash
    sudo -u factory-agent -H bash -lc 'node --version && pnpm --version'
    sudo -u factory git -C /srv/factory/repo worktree add \
      -b console-smoke /srv/factory/worktrees/console-smoke origin/main
    sudo -u factory sudo -n -u factory-agent -- \
      /srv/factory/worktrees/console-smoke/web/console/scripts/check.sh
    # prove a killed check leaves no agent process (and frees port 3000)
    sudo -u factory timeout 20 sudo -n -u factory-agent -- \
      /srv/factory/worktrees/console-smoke/web/console/scripts/check.sh || true
    sudo -u factory-agent /usr/bin/pkill -KILL -u factory-agent
    pgrep -u factory-agent || echo "no factory-agent processes left"
    sudo -u factory git -C /srv/factory/repo worktree remove --force \
      /srv/factory/worktrees/console-smoke
    sudo -u factory git -C /srv/factory/repo branch -D console-smoke
    ```
    `pgrep` must print nothing; the `|| echo` only makes that expectation
    visible. The console check runs `pnpm install --frozen-lockfile
    --prefer-offline` from the repo root and `pnpm exec playwright install
    chromium` before the checks, so a fresh worktree passes; both are fast when
    the pnpm store and the browser cache are warm. The check runner also sets
    `CI=true` for the console area, so Playwright never reuses a dev server
    already listening on port 3000 from another worktree. Before a console
    check it also verifies port 3000 is free, runs the agent cleanup once if it
    is not, and fails with a clear "port 3000 busy" message if someone else
    still holds it.

6. **Set up the read-only deploy key and clone** as `factory`. Fetching uses
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

    The clone must belong to group `factory`, never to `factory-work` or any
    group `factory-agent` is in. A leftover setgid `factory-work` group makes
    the whole clone writable by the agent. Fix it with:
    ```bash
    sudo chgrp -R factory /srv/factory/repo
    sudo chmod -R g-s /srv/factory/repo
    sudo chmod -R g-w,o-w /srv/factory/repo
    ```
    The preflight walks the whole repo, including `.git`, and fails if any file
    or directory is owned by `factory-agent`, belongs to a group it is in, is
    world-writable, or is a setgid directory in an agent group.

7. **Create the `xolo-bot` GitHub App and install it on the repo only.** The
   factory does **not** store any `gh` auth and does **not** set a global git
   credential helper (a global helper would leak into the OpenCode subprocess).
   Instead:
   - Register a GitHub App (`xolo-bot`) in the machine account's org/personal
     settings, give it `contents` (read/write), `pull requests` (read/write)
     and `issues` (read/write), and install it on `daedraMex/commerce-platform`
     only. Note its App ID and Installation ID, download its private key, and
     note the numeric user id of its bot account from
     `https://api.github.com/users/xolo-bot%5Bbot%5D` (the `id` field). The
     runner commits as `xolo-bot[bot]` using that id, never a machine git
     identity.
   - Save the private key as a file the `factory` user owns, `chmod 600`:
     ```bash
     install -m 600 xolo-bot.pem /home/factory/xolo-bot.pem
     ```
   - The factory mints a short-lived installation token on demand: one for the
     run's `gh` read calls (`list_tickets` and its blocker/PR lookups) and a
     fresh one inside the success and stuck paths. Each token is passed only to
     the subprocesses that need it; it is never stored and never reaches the
     OpenCode subprocess.

8. **Give the agent the model provider key.** Set a **spending cap** on the
   provider account. Log OpenCode in *as `factory-agent`* so the key lives in
   that user's own auth store (`~/.local/share/opencode/auth.json`, mode `600`)
   and never travels through sudo or the environment:
   ```bash
   sudo -u factory-agent -H /usr/bin/opencode auth login   # choose the provider, paste the key
   sudo -u factory-agent -H /usr/bin/opencode auth list    # expect the provider to be listed
   ```
   The factory starts OpenCode with `HOME=/home/factory-agent`, so it finds
   that store on every run. Do **not** put the key in `secrets.env` and do
   **not** set `FACTORY_PROVIDER_ENV_VARS`: passing it through
   `sudo --preserve-env` is exactly what used to write it to the journal. On an
   existing machine, delete any `DEEPSEEK_API_KEY`/`FACTORY_PROVIDER_ENV_VARS`
   lines from `secrets.env` and **rotate that key** (an older install passed it
   through sudo, so the key may already be in the journal). The machine must
   never receive the production, R2, payment or per-store integration
   credentials, and never the real `.env`.

   Then create the agent's **read-only OpenCode config home**. Every OpenCode
   run gets `XDG_CONFIG_HOME` pointing here (`FACTORY_AGENT_CONFIG_HOME`,
   default `/srv/factory/agent-config`), so the global config is something the
   agent can read but never write; its own `~/.config/opencode/` is ignored. The
   auth store stays in `~/.local/share/opencode/`, which `XDG_CONFIG_HOME` does
   not move. OpenCode creates `<config home>/opencode` at startup, so that
   subdirectory must already exist:
   ```bash
   sudo install -d -o factory -g factory -m 0755 /srv/factory/agent-config
   sudo install -d -o factory -g factory -m 0755 /srv/factory/agent-config/opencode
   ```
   Leave `opencode/` empty unless OpenCode needs global settings; if it does,
   review the file and put it there (owned by `factory`, mode `0644`).

   OpenCode also loads `~/.opencode/` (config and plugins) from the agent's home
   even with project config disabled, and `~/.claude/` and `~/.agents/` unless
   switched off. Every run sets `OPENCODE_DISABLE_CLAUDE_CODE=1` and
   `OPENCODE_DISABLE_EXTERNAL_SKILLS=1`, and before every OpenCode run the
   factory checks that none of `~/.opencode`, `~/.claude` or `~/.agents` exists
   in `/home/factory-agent`; if one does, the run stops and names it. Review
   any of them (and the old `~/.config/opencode/`, now ignored) and remove them:
   ```bash
   sudo ls -la /home/factory-agent/.opencode /home/factory-agent/.claude \
     /home/factory-agent/.agents /home/factory-agent/.config/opencode
   strings /usr/bin/opencode | grep -c OPENCODE_DISABLE_CLAUDE_CODE      # expect > 0
   strings /usr/bin/opencode | grep -c OPENCODE_DISABLE_EXTERNAL_SKILLS  # expect > 0
   ```
   The preflight fails if the config home or its `opencode/` is missing or
   writable by the agent, if the agent cleanup (`pkill` through sudo) does not
   work, or if OpenCode cannot start as the agent with the real environment.

9. **Create the secrets file** `~/factory/secrets.env`, `chmod 600`, with the
   settings the factory reads from the environment:
    ```bash
    FACTORY_MODEL=deepseek/deepseek-flash        # the cheap default model
    FACTORY_STRONG_MODEL=deepseek/deepseek-v4-pro # for strong-model tickets
    FACTORY_TELEGRAM_BOT_TOKEN=123456:ABC...     # from @BotFather
    FACTORY_TELEGRAM_CHAT_ID=123456789           # the one fixed chat id
    XOLO_BOT_APP_ID=123456                       # the xolo-bot App ID
    XOLO_BOT_PRIVATE_KEY=$HOME/factory/xolo-bot.pem   # path to the private key file
    XOLO_BOT_INSTALLATION_ID=987654              # the installation on this repo
    XOLO_BOT_USER_ID=1234567                     # xolo-bot[bot] user id, for commits
    # agent isolation (the provider key is in factory-agent's own auth store):
    FACTORY_AGENT_USER=factory-agent
    FACTORY_AGENT_HOME=/home/factory-agent
    FACTORY_HOST=factory@factory-host            # ssh target for the stuck handoff
    # run limits (both must be >= 1):
    FACTORY_MAX_OPEN_PRS=2                       # open xolo-bot PRs on nf/* branches
    FACTORY_MAX_TICKETS_PER_DAY=6                # attempts started today, failures included
    FACTORY_STATE_DIR=/home/factory/state        # pause marker + append-only attempts ledger
    # other optional overrides:
    # FACTORY_MAX_TICKETS=1
    # FACTORY_ATTEMPTS=3              # max agent steps per ticket
    # FACTORY_PRE_PR_REVIEW=1         # 0 turns the pre-PR reviewer off
    # FACTORY_AGENT_CONFIG_HOME=/srv/factory/agent-config  # agent's read-only OpenCode config
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

10. **Create the Telegram bot** with [@BotFather](https://t.me/BotFather),
   take its token into `FACTORY_TELEGRAM_BOT_TOKEN`, and find the one chat id
   the bot sends to (message the bot, then read the chat id from the
   `getUpdates` response, then disable updates — the bot only sends, it never
   polls or accepts commands).

11. **Install the systemd user units** as `factory`:
    ```bash
    mkdir -p ~/.config/systemd/user
    cp /srv/factory/repo/tools/factory/systemd/factory.service ~/.config/systemd/user/
    cp /srv/factory/repo/tools/factory/systemd/factory.timer  ~/.config/systemd/user/
    cp /srv/factory/repo/tools/factory/systemd/factory-metrics.service ~/.config/systemd/user/
    cp /srv/factory/repo/tools/factory/systemd/factory-metrics.timer  ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now factory.timer
    systemctl --user enable --now factory-metrics.timer
    loginctl enable-linger factory   # keep the timer alive when nobody is logged in
    ```
    The timer fires hourly. `factory.service` is `Type=oneshot`, so systemd
    never starts a run while the previous one is still active. After changing a
    unit file, reload and restart the timer:
    ```bash
    systemctl --user daemon-reload && systemctl --user restart factory.timer
    ```

12. **Protect `main`.** `.github/CODEOWNERS` contains `* @daedraMex`. On
    GitHub: require a pull request before merging, require 1 approval, turn on
    **Require review from Code Owners**, and require the "Backend" and "Ticket
    link" checks. Do not give the factory or any agent a bypass. The repository
    admin (the owner) may bypass the ruleset in a pull request, but only to
    merge her own human pull requests, which GitHub does not let her approve;
    factory pull requests always go through her approval. Agents (the factory,
    evaluators and reviewers) never approve.

## Migrating an existing machine

To upgrade an existing machine to this version:

1. Update `/etc/sudoers.d/factory-agent` to the file shown in the setup steps
   and validate it with `sudo visudo -c`.
2. Run `opencode auth login` as `factory-agent`:
   `sudo -u factory-agent -H /usr/bin/opencode auth login`.
3. Remove `DEEPSEEK_API_KEY` and `FACTORY_PROVIDER_ENV_VARS` from
   `~/factory/secrets.env`, and add `XOLO_BOT_USER_ID`.
4. Rotate the DeepSeek key and the Postgres password, because both appeared in
   the journal.
5. Create the state directory (`install -d -m 700 /home/factory/state`), add
   `FACTORY_MAX_OPEN_PRS` and `FACTORY_MAX_TICKETS_PER_DAY` to
   `~/factory/secrets.env` if you want non-default caps, and copy the current
   `factory.service`/`factory.timer` into `~/.config/systemd/user/`. Then reload
   and restart the hourly timer:
   ```bash
   systemctl --user daemon-reload && systemctl --user restart factory.timer
   ```
6. Clean any leftover worktrees, then run `factory preflight`.

## How tickets become agent-ready

- When `/to-tickets` creates a ticket it is marked **HITL** (human-in-the-loop)
  or **AFK** (away-from-keyboard). Only **AFK** tickets may later get the
  `ready-for-agent` triage label.
- A ticket is **agent-ready** when it has `ready-for-agent`, all its blocking
  edges are closed, it has no open PR, it is not labeled `needs-decision`, and
  no open PR holds one of its contracts (ADR-0031). The factory reads each
  ticket's **Contracts** section (backticked ids after Defines, Changes or
  Consumes) and the same section of every ticket an open PR, by any author,
  closes. A ticket waits when it defines or changes a contract the open PR's
  ticket touches, or consumes one that ticket defines or changes; two tickets
  that only consume a contract never wait for each other. Each id takes the
  nearest verb before it; an id with no verb counts as changed. If an open PR's
  ticket cannot be read, every ticket that declares contracts waits (`contracts
  of #<ticket> unreadable`) and the rest of the run goes on. Each run logs
  `#<n> skipped: <contract> held by PR #<pr> (#<ticket>)` for a ticket that
  would otherwise be ready, and one run never takes two tickets that conflict
  on a contract.
- Add `strong-model` to a ticket that touches security, money, migrations or
  otherwise tricky logic; it runs with `FACTORY_STRONG_MODEL` instead of the
  default. The builder model is never the reviewer of its own work.
- Migrations and changes touching money, security or customer data still get a
  human review before merging (unchanged AGENTS.md safety rules).
- `FACTORY_MAX_TICKETS` (default 1) is how many independent tickets one run
  takes, oldest first, each on its own branch. Keep it at 1 with the hourly
  timer: the daily cap is checked at the start of a run, so raising this can
  exceed the daily attempt count. The run still stops at the first failure.

## Run limits and pauses

Two caps stop the factory before it picks a ticket:

- **Open-PR cap.** `FACTORY_MAX_OPEN_PRS` (default 2) counts open pull requests
  authored by `xolo-bot` on `nf/*` branches, draft or ready. At the configured
  value the run pauses with "N PRs waiting for review". A review fix on one of
  those existing PRs still runs, because it does not add another open PR.
- **Daily cap.** `FACTORY_MAX_TICKETS_PER_DAY` (default 6) counts ticket
  *attempts* started today in `America/Mexico_City`, successful or failed. At
  the configured value the run pauses with "daily limit reached". A `started`
  line is written before OpenCode runs and an outcome line after it finishes;
  the daily cap counts only `started` lines, so a run killed by systemd's
  timeout, a reboot or SIGTERM still consumes budget. The ledger at
  `/home/factory/state/attempts.log` is append-only, mode `600`, and stays
  unreadable by `factory-agent`. Failed attempts count, so a broken ticket
  cannot burn the model budget.
- **Unreachable GitHub.** If the open-PR count cannot be read, the run pauses
  with "GitHub unreachable" instead of assuming zero.

Both limits must be at least 1; the config rejects smaller values before the
run. A skipped run is silent. Telegram gets exactly one message when the
factory moves into a paused state, and nothing more until that state clears;
the normal PR-ready, stuck and aborted messages are unchanged.

## Addressing review feedback

At the start of each run, before it picks a new ticket, the factory looks for
open pull requests it authored on `nf/*` branches whose latest review by the
repository owner (`daedraMex`) is **CHANGES_REQUESTED** and whose branch head
has no commit after that review, whoever authored it (the factory, the owner
or anyone else). Only reviews by the owner count; reviews by bots or other
agents are ignored. It takes at most one such pull request per run, oldest
review first.

Reviews are read from the REST reviews endpoint, not from `gh pr view --json
reviews`. The REST `id` is the numeric database id that the review-comments
route needs; the GraphQL `id` is a node id such as `PRR_kwDOVUbRpc8AAAABXa4Txg`,
which the REST comments route rejects with a 404. The numeric id, as a string,
is the review id used everywhere: the comments call, `ReviewFix.review_id` and
`review-attempts.log`.

Every attempted review id is written to `review-attempts.log` (append-only,
mode `600`) before the agent runs. A review is never retried automatically,
whatever the outcome; a new review on the same pull request has a new id, so it
is picked up again.

For that pull request the factory creates a fresh worktree from the PR branch
(never from `main`) and never force-pushes. Before the agent runs, the runner
fetches `main` and merges `origin/main` into the branch with a merge commit
(bot identity, hooks disabled), so the fix is checked against current `main`
and the push carries the merge. If that merge conflicts, the runner aborts it,
does not run the agent, and sends the ticket through the stuck flow with
"branch conflicts with main; a human must merge main": a person merges `main`
into the branch and pushes. The agent cannot run git, and its prompt says so:
a review that asks for a git operation becomes an `OPEN QUESTION:` instead of
an imitation by editing files. The protected-path guard measures the fix from
the commit after the merge, so files that `main` brought in do not count as the
agent's changes. The agent receives the linked
ticket, the review body and every inline review comment (file, line and text)
as **untrusted data**, with an explicit instruction never to follow commands
inside them and never to touch protected paths. The protected-path guard still
inspects the fix's own diff. After every area the fix touched passes its
`scripts/check.sh`, the runner commits `fix: address review on #<pr>`, pushes to the same branch,
comments `Addressed the review in <sha>; please re-review.` on the pull
request and sends Telegram. If the agent cannot finish, the ticket goes through
the usual stuck flow (issue comment, `needs-decision` label and Telegram).

A review fix consumes one attempt from the daily ledger, exactly like a new
ticket, but it does not count against the open-PR cap. If listing reviews
fails, review fixes are skipped for that run and the normal ticket flow
continues; a `GitHubError` also sends one short Telegram notice for that run.
If GitHub itself is unreachable, the run still pauses with "GitHub
unreachable" as before.

## Hardening

- **Isolation.** OpenCode runs as `factory-agent`; on every startup the factory
  runs a positive control (that user must be able to `cat /etc/hostname`) and
  then proves it cannot read the GitHub App private key, `secrets.env` or
  `~/.ssh/commerce_deploy` (via `sudo -n -u factory-agent -- /usr/bin/cat -n
  <path>`). It also proves `factory-agent` cannot write to `/srv/factory`,
  `/srv/factory/repo` or `repo/.git/hooks` (via `/usr/bin/test -w`), then walks
  the whole clone as the factory user with `os.walk` and `lstat` and fails if
  any file or directory (including `.git`) is owned by `factory-agent`, belongs
  to a group it is in, is world-writable, or is a setgid directory in an agent
  group. Any result other than a clean "permission denied" or "not writable",
  or any unsafe path in that walk, aborts the run, so a broken sudo rule fails
  closed.
- **Env allowlist.** The factory launches `/usr/bin/opencode` as
  `sudo -n --preserve-env=<explicit list> -u factory-agent -- /usr/bin/opencode
  ...` with an explicit environment — `PATH`, `HOME` (the agent's home), `LANG`,
  `DATABASE_URL`, `XDG_CONFIG_HOME` (the read-only config home),
  `OPENCODE_DISABLE_CLAUDE_CODE`, `OPENCODE_DISABLE_EXTERNAL_SKILLS` and
  `OPENCODE_CONFIG_CONTENT` (main's `opencode.factory.json` for the builder,
  `opencode.reviewer.json` plus `OPENCODE_DISABLE_PROJECT_CONFIG` for the
  reviewer) — nothing else. An inline config outranks the repo's
  `opencode.json`, which a file named by `OPENCODE_CONFIG` does not; its
  permissions are also set as the `build` agent's, which the repo's
  `opencode.json` defines. A blank or invalid config on `origin/main` fails the
  run. After every OpenCode run and every set of area checks, the factory kills
  every process the agent user still has, repeating while `pkill` finds some; a
  cleanup sudo refuses fails the run, so nothing the agent started can change
  files later. The model
  provider key is
  not in it: the agent reads its own OpenCode auth store from its home, so the
  key never crosses sudo. The backend check runner gets the same downgrade with
  only `PATH`, `HOME`, `LANG` and `DATABASE_URL`, plus a fixed set of non-secret
  test settings (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `REDIS_URL`,
  `PYTEST_ADDOPTS=-p no:cacheprovider`) that match CI's backend job so Django
  can start without a worktree `.env`: no provider key, no GitHub token, no
  secrets. The console check runner gets only `PATH` (with the system-wide
  Node), `HOME` (the agent's home), `LANG`, `CI=true` and
  `PLAYWRIGHT_BROWSERS_PATH` under that home, so Playwright installs and reads
  its browser there and never reuses a dev server from another worktree. The
  agent gets the same test settings. `PYTEST_ADDOPTS` keeps pytest from writing
  a cache into the worktree. They are constants in the factory code and are
  never read from `secrets.env`.
- **Commit identity.** The runner stages and commits with an explicit
  `-c user.name=xolo-bot[bot] -c user.email=<id>+xolo-bot[bot]@users.noreply.github.com`
  built from `XOLO_BOT_USER_ID`, so it never depends on a machine `git config`.
  The preflight runs `git var GIT_AUTHOR_IDENT`/`GIT_COMMITTER_IDENT` with the
  same args (a dry check that creates no commit) and fails if the id is missing
  or unusable. The agent never commits; it leaves its changes in the worktree.
- **Sudo journal.** The preflight runs `sudo -n -l` as `factory` and fails on a
  non-zero exit or unless the effective "Matching Defaults entries" contain
  `!log_allowed`, so successful downgrade commands (with their environment and
  prompt) stay out of the journal. Denied commands are still logged. If
  `sudo -n -l` would need a password, the run stops instead of proceeding
  unverified.
- **Secret rotation.** If any secret (the model provider key, the Telegram bot
  token or the xolo-bot private key) ever appears in the journal, a log file, a
  pull request or anywhere else it should not, treat it as compromised and
  **rotate it**: re-run `sudo -u factory-agent -H /usr/bin/opencode auth login`
  for the provider key, issue a new Telegram token and update `secrets.env`, or
  regenerate the xolo-bot key and replace `xolo-bot.pem`, then restart the
  timer. Deleting the log line is not enough.
- **Per-ticket budget.** Each ticket has a step budget (`FACTORY_ATTEMPTS`,
  default 3) and a time budget (`FACTORY_TIME_LIMIT_MINUTES`). Exceeding either
  stops the ticket as stuck and notifies Telegram. Each ticket fetches
  `origin/main` itself before creating its worktree.
- **Pre-PR review.** After every selected area's check passes, the factory
  first applies the protected-path guard (a change there goes stuck before any
  review), then a reviewer (`FACTORY_STRONG_MODEL`) reviews the diff in a fresh
  OpenCode session. Its permissions are main's `opencode.reviewer.json` (no
  edits, no shell), passed inline as `OPENCODE_CONFIG_CONTENT` with
  `OPENCODE_DISABLE_PROJECT_CONFIG=1`: an inline config outranks the repo's
  `opencode.json` and `.opencode/`, which a file named by `OPENCODE_CONFIG` does
  not. It applies `REVIEW.md` read from `origin/main`, never from the worktree,
  and answers in a `REVIEW-FINDINGS` block. Important findings go back to the
  builder and stay in its prompt until a review passes; when the step budget
  ends with one open, the ticket goes stuck as `review: <file:line> <summary>`.
  Nits, Pre-existing findings and unparsed reviewer lines go to the PR body. A
  reviewer that changes the worktree sends the ticket to stuck; a reviewer that
  times out or answers without a findings block is reported in the PR body
  ("read in full") and the PR still opens. `strong-model` tickets skip the
  review, because the builder model never reviews its own work;
  `FACTORY_PRE_PR_REVIEW=0` turns it off. Known gap (#158): the agent's home
  (`/home/factory-agent`) is still its own and is reused across runs, and
  OpenCode reads from it at every start (`auth.json`, its local database, the
  cached `rg`, `~/.gitconfig`). A builder could use it to blind the reviewer in
  later runs; the reviewer is advisory, and the owner's approval, the
  protected-path guard and the worktree fingerprint still gate every PR.
- **Pull request body.** Besides the summary and decisions, every factory PR
  lists under **Verification** each area check script that passed or was
  skipped and the agent steps used, under **Review** the pre-PR review's
  outcome and non-blocking findings, under **Risk** changed migrations, console
  check configuration (`CHECK_CONFIG_NAME_PATTERNS` in `diff.py`: `vitest.config.*`,
  `playwright*.config.*`, `tsconfig*.json` and similar, which
  decide what the checks see, so read them in full) and sensitive paths
  (`SENSITIVE_PREFIXES` in `diff.py`), and under **How to revert** what undoing
  the merge takes.
- **Areas.** Each ticket's changed files select its check areas: `backend/**`
  runs `backend/scripts/check.sh`, and `web/console/**` or `packages/**` runs
  `web/console/scripts/check.sh` (so a backend ticket that refreshes
  `packages/api-client/openapi.json` runs both). A docs-only ticket runs every
  area, and an area whose script is absent is skipped and logged rather than
  failed.
- **Fix loop.** Before pushing, the factory runs every selected area's
  `scripts/check.sh` in the worktree **as `factory-agent`**, sequentially, each
  in its own process group with its own timeout, with only that area's env
  allowlist. The output is labelled per area and truncated; on failure it
  feeds a truncated tail back to the agent, naming the real failing area and
  script, and retries up to the step budget.
- **Timeout cleanup.** Sending signals across users does not work — the factory
  cannot kill `factory-agent` children, so killing the process group from the
  factory user only reaps sudo. On a timeout the factory first sends SIGTERM to
  sudo (which relays it to the command), waits up to 20 seconds, then runs
  `sudo -n -u factory-agent /usr/bin/pkill -KILL -u factory-agent` to kill every
  remaining agent process. The same cleanup runs after an OpenCode timeout, so
  no `next`, Playwright or Chromium process survives to hold port 3000. Before a
  console check the factory verifies port 3000 is free; if it is busy it runs
  that cleanup once and, if the port is still busy, fails with a clear
  "port 3000 busy" message instead of a confusing Playwright error.
- **Worktree cleanup.** Stale and expired worktrees are deleted as their owner
  with the sudoers-allowed `rm -rf` (direct children only; paths outside the
  worktrees directory or containing `..` are refused), then `git worktree
  prune` runs and the local branch is deleted. Every cleanup step checks its
  exit code and raises, so a failed cleanup stops the run instead of leaving a
  directory that blocks the next worktree. The preflight also fails if the
  worktrees directory contains entries that are not live git worktrees, and
  creates an agent-owned directory with group `factory-agent` and mode `0770`
  inside the throwaway worktree to prove the same cleanup removes it.
- **Protected paths.** Before the pre-PR review and again before pushing, the
  factory inspects the diff. If it touches `.github/`, `tools/factory/`,
  `backend/scripts/`, `backend/tests/architecture/`, `web/console/scripts/`,
  `.opencode/`, `AGENTS.md`, `CLAUDE.md`, `REVIEW.md`, `.pre-commit-config.yaml`,
  any `opencode*.json[c]`, any `conftest.py`, any backend check configuration
  that outranks `pyproject.toml` (`pytest.toml`, `.pytest.toml`, `pytest.ini`,
  `.pytest.ini`, `setup.cfg`, `tox.ini`, `ruff.toml`, `.ruff.toml`), or any guard
  configuration (`eslint.config.*`, `.eslintrc*`, `.importlinter`: lint rules and
  architecture tests are where an agent's recurring mistake becomes a guard; no
  label unlocks any of these), the ticket goes to `_stuck` with `protected path
  changed`; nothing is pushed and no PR is opened. Dependency manifests and
  lockfiles (`package.json`, `pnpm-lock.yaml`, `pyproject.toml`, `uv.lock`) are
  protected the same way unless the ticket is labeled `deps-change`. Even then a
  manifest may change only its dependency sections (`dependencies`,
  `devDependencies`, `optionalDependencies`, `peerDependencies`, `pnpm`;
  `[project].dependencies`, `optional-dependencies`, `[dependency-groups]`,
  `[tool.uv].sources`): a change to `scripts` or `[tool.*]` goes stuck as
  `dependency file changed beyond dependencies`. The PR (or the review fix's PR)
  gets the `deps-change` label and lists the files under **Risk**; the factory's
  own lockfiles under `tools/factory/` stay protected. `opencode.factory.json`
  denies edits to the same paths (a test keeps the two lists in sync), and every
  push is checked to target the ticket's own `nf/<number>-<slug>` branch.
- **Stuck handoff.** A stuck ticket keeps its worktree; the Telegram message
  includes the `ssh` + `cd` command to enter it.

## Level 2 E2E

The "Level 2 E2E" GitHub Actions check runs a few critical Playwright flows in
`web/console/e2e-level2/` against Django, Celery, PostgreSQL, Redis and RustFS.
It is a required check when a pull request changes `backend/`,
`web/console/`, `packages/` or `.github/workflows/`; otherwise the job reports
success without starting the stack. The night factory never runs it, because it
would need Docker for the agent user (ADR-0026).

RustFS runs outside the `services:` block because it needs a writable data
mount. The job starts the pinned `rustfs/rustfs` image with `docker run -d`,
generates and masks its access key and secret, and creates both buckets with
the pinned `amazon/aws-cli` image. The public bucket gets an anonymous
`s3:GetObject` bucket policy; the private bucket gets none. The job then proves
it anonymously with `curl`: a public probe object returns 200 and a private one
returns 403 with `AccessDenied`. Finally it exports the `R2_*` variables so the
backend and worker use those buckets.

Run it locally from the repository root. These are the same commands as the
job, with a fixed password:

```bash
docker compose up -d postgres redis rustfs storage-init
export R2_BUCKET_NAME=catalog-media
export R2_PRIVATE_BUCKET_NAME=catalog-private
export R2_ACCESS_KEY_ID=rustfsadmin
export R2_SECRET_ACCESS_KEY=rustfsadmin
export R2_ENDPOINT_URL=http://127.0.0.1:9000
export MEDIA_BASE_URL=http://127.0.0.1:9000/catalog-media
cd backend
uv run python manage.py migrate
DEBUG=True E2E_SEED_ALLOWED=1 E2E_STAFF_EMAIL=e2e@example.com \
  E2E_STAFF_PASSWORD=local-e2e uv run python manage.py e2e_seed
uv run python manage.py runserver 127.0.0.1:8000 --noreload &
uv run celery -A config worker --loglevel=info &
cd ..
pnpm install --frozen-lockfile
pnpm generate:client
cd web/console
API_BASE_URL=http://127.0.0.1:8000 pnpm build
API_BASE_URL=http://127.0.0.1:8000 pnpm exec next start -p 3100 &
E2E_BASE_URL=http://127.0.0.1:3100 E2E_API_URL=http://127.0.0.1:8000 \
  pnpm exec playwright test --config playwright.level2.config.ts
```

`docker compose up -d postgres redis rustfs storage-init` starts only the
dependencies; the API, the worker and the console run on the host exactly as
they do in the job. The `storage-init` service creates the public and private
buckets; without the exported `R2_*` variables the backend would fall back to
local files. The job generates a random staff password with `openssl rand`,
masks it with `::add-mask::` and passes it through `E2E_STAFF_PASSWORD`; no
secret is stored.

## Ratchet rule

Every bug found in a factory PR review or a failed night becomes a test or a
preflight step in the same fix, so that class of error cannot recur silently.
A fix that only changes the code, without adding the failing test or preflight
step that would have caught it, is not finished. For example, the symlink false
positive in the repo-tree walk (a symlink's `lrwxrwxrwx` is not
world-writable) became the symlink tests in `tests/test_isolation.py`. The
review-fix 404 (a GraphQL node id sent to a REST comments route) became the
recorded REST review fixture and the numeric-id tests in
`tests/test_github.py`. A review that asked to merge `main` (PR #119) made the agent re-type
`main`'s code by hand, because it cannot run git; that became the runner-side
merge before every review fix and the conflict, ordering and prompt tests in
`tests/test_main.py`, `tests/test_git.py` and `tests/test_prompt.py`.

## Reading logs and decisions

- Each run writes `~/factory/logs/<ticket>.log`. Read the tail of the log to
  see what the agent did and why it failed.
- The agent keeps a running decision log in `DECISIONS.md` at the worktree
  root (git-ignored, never committed). It holds every choice, the rejected
  alternative, and why. If the agent could not decide safely it writes the open
  question as the first line, starting with `OPEN QUESTION:`.
- Worktrees and logs older than 14 days are deleted at the start of each run
  that is not paused.

## Answering a `needs-decision` ticket

A stuck ticket gets a comment (open question + decisions so far + last log
lines) and the `needs-decision` label. To unblock it:

1. Open the issue and read the comment.
2. Answer the open question (or edit the ticket).
3. Remove `needs-decision`. The next run picks it up again if it is still
   `ready-for-agent`.

If the label cannot be added (the label is missing, or GitHub fails), the
Telegram message says so and the factory holds the ticket in
`label-holds.log` in its state directory. Every run retries the label before
picking tickets and drops the hold once it lands; a held ticket is never run.
If the issue comment failed instead, the run fails loudly and the retried label
arrives without a comment: read the log before removing `needs-decision`. To
release a hold by hand, delete the ticket's `#<number>` line from that file.
Labeling a pull request (`migration`, `deps-change`) raises the same way: a new
PR stays a draft without auto-merge, and a review fix is labeled before its
push, so a failure pushes nothing.

## Preflight

Run the preflight first after any machine or factory change, and before the
first real night:
```bash
cd /srv/factory/repo/tools/factory
set -a; source ~/factory/secrets.env; set +a
uv run factory preflight
```

It uses the real tools and the real code paths, not fakes: it fetches
`origin/main`, lists tickets through the `gh` code path, fails if a label the
factory reads or writes is missing (`REQUIRED_LABELS` in `tickets.py`; the
message gives the `gh label create` command for each), creates a throwaway
`preflight-<timestamp>` worktree from the fresh `origin/main`, runs every
present area's `check.sh` in it as `factory-agent` with the real check
environment, verifies isolation,
the git version, the bot commit identity and the effective sudo `!log_allowed`
policy, fails if the worktrees directory contains entries that are not live git
worktrees, then proves the cleanup removes an agent-owned
`factory-agent:factory-agent` 0770 directory and deletes the worktree and
branch even on failure.
Any failed step sends `preflight failed: <step>: <short error>` to Telegram
(truncated, with no environment values or secrets) and exits non-zero without
touching a ticket. The hourly run performs the same preflight before selecting
any ticket. The ticket then fetches `origin/main` again for its own worktree, so
its base can be newer than the `main` the preflight checked; a fetch failure at
that point counts as a failed attempt toward the daily cap.

## Run once by hand

As `factory`:
```bash
cd /srv/factory/repo/tools/factory
set -a; source ~/factory/secrets.env; set +a
uv run factory
```

## Weekly metrics

`factory metrics` sends one Telegram message with the review metrics for the
factory's PRs (`xolo-bot`, `nf/*`) over the last 7 and 28 days, each number
windowed by the date of its own event: PRs opened and merged; of the merged
ones, how many were clean (reviewed, no change requested), how many had no
owner review, the change-request rounds and the open-to-merge hours; the
owner's wait by review date (from ready for review to her first review, and
from each "Addressed the review" comment to her next review); the PRs still
waiting for her and the oldest wait; stuck tickets and reverts. It reads the
GitHub REST API with a freshly minted installation token and changes nothing.
`factory-metrics.timer` runs it on Mondays at 09:00 `America/Mexico_City`; a
failure to collect sends one `metrics failed: ...` message, and a report that
Telegram does not accept makes the command exit non-zero. By hand:
```bash
cd /srv/factory/repo/tools/factory
set -a; source ~/factory/secrets.env; set +a
uv run factory metrics
```

## Stopping it

```bash
systemctl --user stop factory.timer   # stop the schedule
systemctl --user stop factory.service # stop a run in progress
systemctl --user stop factory-metrics.timer   # stop the Monday metrics
```

To see when the next run is scheduled:
```bash
systemctl --user list-timers 'factory*.timer'
```
