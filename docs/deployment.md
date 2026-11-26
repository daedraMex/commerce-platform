# Deployment

How the platform runs in staging and production. Phase 6a runs on one VPS with
Dokploy, Cloudflare DNS, Cloudflare R2 and GitHub Actions releases. ADR-0010
(host), ADR-0026 (Quetzal), ADR-0035 (label links), ADR-0036 (releases) and
ADR-0037 (observability) record the decisions; this file is the runbook.

## Environments

| | Production | Staging |
|---|---|---|
| Purpose | staff's real work | pre-production check |
| API | `api.berlekgroup.com` | `api.staging.berlekgroup.com` |
| Quetzal | `consola.berlekgroup.com` | `consola.staging.berlekgroup.com` |
| Label links | `q.berlekgroup.com` | not public |
| Public media | `media.berlekgroup.com` | `media-staging.berlekgroup.com` |
| Database | own | own |
| Buckets | `berlek-media-prod`, `berlek-private-prod`, `berlek-backups-prod` | `berlek-media-staging`, `berlek-private-staging`, `berlek-backups-staging` |
| Secrets | Dokploy prod project env; GitHub `production` | Dokploy staging project env; GitHub `staging` |

Every layer is separate: database, buckets, tokens and secrets. Staging is
`noindex`. Production is the only environment that takes real photos and staff
work.

Both environments share the one VPS. Staging runs with tighter memory limits and
can be stopped at any time; production always has priority. A staging redeploy
never restarts production containers.

## Host

Hostinger VPS KVM 2: 2 vCPU, 8 GB RAM, 100 GB NVMe, US region, Ubuntu 24.04.
Root access is SSH key only. The 30-day refund window ends 26 December 2026, so
the platform must be deployed and tested from a phone before then.

### Hardening checklist

- Root login by SSH key only; password authentication disabled.
- A non-root `deploy` user owns Dokploy and operational scripts.
- `ufw` allows only 22, 80 and 443.
- **Docker-published ports bypass `ufw`.** Postgres and Redis never publish a
  port. The Dokploy dashboard (port 3000) is never reachable from the internet:
  serve it on its own HTTPS domain with strong login and 2FA, or reach it only
  through an SSH tunnel; confirm from outside that :3000 is closed.
- Official Docker Engine and Compose from Dokploy's installer.
- Unattended security upgrades on.
- Per-container memory limits in `docker-compose.prod.yml` so 8 GB is shared
  predictably between api, worker, beat, console, Postgres and Redis, with
  staging's limits tighter than production's.
- Weekly Hostinger snapshot enabled.

## DNS (Cloudflare)

`berlekgroup.com` is served by Cloudflare. **Before** the nameserver switch,
export every record from the old cPanel Zone Editor and recreate MX, SPF, DKIM,
DMARC, autodiscover and mail in Cloudflare, so email keeps working.

- `api`, `consola`, `q`, `api.staging`, `consola.staging` → `2.25.195.210`,
  **DNS-only (grey cloud)**.
- `media` and `media-staging` are R2 custom domains (proxied; single-level
  because Universal SSL covers `*.berlekgroup.com`, not two-level names).
- TLS: Dokploy's Traefik issues and renews Let's Encrypt certificates per host.
- `q.berlekgroup.com` is frozen and never changes (ADR-0035).

The DNS/TLS work is blocked until `berlekgroup.com` recovers from the WHOIS
suspension (verified 26 November 2026, 24–48 h).

## Dokploy

- One Dokploy **Compose project per environment**, both pointed at
  `docker-compose.prod.yml`, with the services `api`, `worker`, `beat`,
  `console`, `migrate`, `postgres` and `redis`. It is one project per
  environment, not a separate Dokploy application per service.
- Every service joins `dokploy-network` and gets its domain through the Traefik
  labels Dokploy expects; no second proxy.
- Dokploy pulls the images from private GHCR with a read-only `read:packages`
  token.
- Runtime secrets are Dokploy environment variables per environment (see
  Secrets). GitHub Environments hold CI/deploy secrets.
- Resource limits are declared in the compose file, not typed into the UI.

## Database extensions

The catalog search is accent-insensitive and needs PostgreSQL's `unaccent`
extension. The `catalog` migration `0003_unaccent` runs
`CREATE EXTENSION IF NOT EXISTS unaccent`.

The database role that runs migrations must therefore be allowed to run
`CREATE EXTENSION`, or a platform operator must create the extension in each
environment before migrating:

```sql
CREATE EXTENSION IF NOT EXISTS unaccent;
```

The migration is reversible: rolling it back drops the extension.

## Storage (R2)

Two public media buckets, two private origin buckets and two backup buckets, one
of each per environment. The public buckets have no anonymous bucket policy;
public read comes only from an R2 custom domain. The private and backup buckets
have no public access at all. `r2.dev` is disabled on every bucket. Each
environment has its own bucket-scoped token.

`MEDIA_BASE_URL` is `https://media.berlekgroup.com` in production and
`https://media-staging.berlekgroup.com` in staging. Stored objects keep the
`public, max-age=31536000, immutable` cache header the code sets.

## External accounts and keys (one-time)

Created by the owner before the first deploy:

- Six R2 buckets (two public media, two private originals, two backups) with
  lifecycle rules: `daily/` expires after 30 days, `monthly/` after 365 days,
  `predeploy/` after 30 days.
- Bucket-scoped R2 tokens, one set per environment.
- An age keypair; the private key goes to the password manager and a GitHub
  secret for the restore job, the public key to the app environment.
- A Telegram bot and chat for alerts.
- Sentry projects and Better Stack monitors/heartbeats.
- GitHub Environments `staging` and `production`; production secrets are bound
  to `v*` tag deployments.

The password manager holds a **secrets inventory**: each secret's name, where it
is set (Dokploy or GitHub), what uses it, and how to rotate it.

## Secrets

- Runtime secrets live in Dokploy environment variables, one set per
  environment. Nothing secret is in the repo, the image or `.env` on disk;
  `.dockerignore` excludes `.env`.
- CI and deploy secrets live in GitHub Environments. The Dokploy API token is
  effectively admin and is treated as the most sensitive CI secret.
- `SECRET_KEY` is distinct per environment and unrelated to credentials.
- `CREDENTIALS_ENCRYPTION_KEYS` is a Fernet key list (ADR-0020): the first key
  encrypts, every key decrypts, so rotation prepends a key. It is never
  `SECRET_KEY`, never in the repository, and never in a database backup. A copy
  lives offline in the password manager.
- Backups are encrypted with age's public recipient on the VPS; only the
  restore job holds the private identity. A compromised VPS or R2 cannot decrypt
  a dump.
- `DEBUG=False`, Sentry PII off, secrets masked in CI, and no secret logged.

## Backups

The weekly Hostinger snapshot covers the whole VM. The restore path we test is a
logical PostgreSQL dump kept off the VPS.

- Daily `pg_dump -Fc` of the app database plus `pg_dumpall --globals-only`, at
  03:00 America/Mexico_City.
- Dumps are age-encrypted before upload to the environment's backup bucket.
- Prefixes and lifecycle: `daily/` (30 days), `monthly/` (365 days, with the
  day-1 dump also written here), `predeploy/` (30 days).
- A production deploy writes a `predeploy/` dump **before** running migrations.
- Staging keeps 7 daily dumps only: no monthly and no restore test.
- A weekly **GitHub Actions** job restores the newest production dump into a
  throwaway Postgres of the same major version (read from
  `docker-compose.prod.yml`), runs `migrate --check` and a row-count smoke
  check, and alerts Telegram on failure. It uses a read-only bucket token.
- A restored database without `CREDENTIALS_ENCRYPTION_KEYS` loses stored
  integration credentials. No credentials exist in 6a; this is a Phase 6
  checklist item.

## Releases

Build once, promote the same bytes (ADR-0036).

- Every green merge to `main` builds the backend and console images, pushes them
  to private GHCR tagged `sha-<gitsha>`, and deploys staging through the Dokploy
  API.
- A `vX.Y.Z` tag that points at an already-built `main` commit retags that exact
  digest as `X.Y.Z` and deploys production. Production never rebuilds.
- One `migrate --noinput` step runs before api, worker and beat start. Workers
  never migrate on boot.
- Migrations are forward-only expand–contract and stay backward-compatible for
  at least one release. No destructive change ships in the release that stops
  using the old form. `manage.py check --deploy` with a production config runs
  in CI.
- After deploy, the pipeline waits for `/api/v1/health/ready/`. If it fails, it
  rolls back to the previous image digest and alerts Telegram. A bad migration
  is fixed forward with a new tag; the schema is never reverted.
- Tags are SemVer from `v1.0.0`. `APP_VERSION` is set to the tag/SHA and
  surfaced by the liveness endpoint. `:staging` and `:prod` are moving aliases;
  the digest is immutable.
- Quetzal reads all configuration at runtime in its server-side BFF. No
  environment-specific `NEXT_PUBLIC_*` value is baked into the image, and a test
  fails if one is introduced, so the staging image is the production image.

## Observability

- **Sentry** (Django, Celery, Quetzal) reports errors; Telegram alerts fire only
  for new issues and regressions, not every event. PII is off.
- **Better Stack** monitors the API readiness endpoint and Quetzal, and holds
  dead-man's-switch heartbeats for the Celery beat sweep and the daily backup.
- **Telegram** (one bot, one chat) receives: new/regression Sentry issue, API or
  Quetzal down, beat or backup missed, weekly restore-test failure, deploy
  result, and disk above 80% or memory above 90%.
- Disk and memory are checked by a small cron script on the VPS that posts
  straight to Telegram; no monitoring agent.
- **No log shipping in 6a.** Every container writes structured JSON to stdout;
  Docker keeps it with `json-file` rotation (10 MB, 3 files) and Dokploy shows
  it. Shipping can be added later without changing the log format.
- Free-tier limits of Sentry and Better Stack are checked when the tickets are
  built; they are not hardcoded here.

## Label redirect (`q.berlekgroup.com`)

The Django backend serves the `q.` host. `GET /<store>/<SKU>` returns a **302**
to a per-store target built from a template, so the printed label never changes
(ADR-0035).

- The 6a target is WhatsApp:
  `https://wa.me/<number>?text=<urlencoded text>`, where the text is
  `Hola <store name>, me interesa <SKU>` and the SKU is URL-encoded. Each store
  may set its own number; otherwise one shared number is used.
- Unknown or inactive stores and SKUs get a minimal friendly **404** page
  ("producto no disponible", plus the store name and link for a known store),
  `noindex`, with no data leak.
- Phase 7 changes only the target template to the storefront product page; the
  link format and route are frozen.

## Initial load (once, in production)

Production starts empty. The operator sheet is the source of truth.

1. `createsuperuser` for the platform operator (plus-addressed email).
2. `create_store` for `anime`, `kawaii`, `llaveros` and `home` **without**
   `--owner`; the command accepts no owner.
3. `create_staff_user --role owner` for the business owner on each store; it
   creates the user and the membership. Then
   `manage.py changepassword <owner-email>` and hand the password over
   out-of-band.
4. `load_catalog_schema --store <slug> --file <schema>` from the versioned
   per-store schema (categories with their option and attribute schemas, plus
   suppliers, including the "Por definir" placeholder). It is idempotent, never
   deletes and never changes a used `sku_code`; `--dry-run` shows the diff first.
5. `import_catalog --store <slug> --csv <rows>` for each store.
6. `verify_catalog_import` reads the same manifest and reports every mismatch in
   stores, categories, suppliers, designs, products, variants and SKUs (prices
   and attributes included). It is read-only, exits nonzero on any mismatch,
   supports `--json` and `--ignore-extra`, and excludes images.
7. Photos from the local database are not migrated; they are taken in
   production. The `sku,quantity` stock sheets are imported in Phase 5.

## Staff accounts

- The **platform operator** is the only superuser and uses it only for the
  Django admin and operations. The operator and the business owner are the same
  person, with two distinct emails (plus-addressing, e.g.
  `name+admin@gmail.com` for the superuser).
- The **business owner** is a normal User with the `owner` role on all four
  stores and `is_staff = False`. The owner uses Quetzal, not the Django admin.
- `create_staff_user --email <e> --store <slug> --role <role>` creates a user
  with an unusable password if absent and grants or keeps the membership. It
  never resets a password and never escalates a role silently.
- The operator sets passwords with `manage.py changepassword <email>` on the VPS
  and hands them over out-of-band. Passwords are never printed or stored in
  plaintext.
- Staff are never superusers; an inactive membership grants nothing.
- No email invites, self-service resets or Quetzal 2FA in 6a.

## Phase 6a exit checklist

- [ ] A staff member signs in to Quetzal in production from a phone.
- [ ] The imported catalog matches its sheets (`verify_catalog_import` clean).
- [ ] A photo taken in production joins the product's carousel.
- [ ] `q.berlekgroup.com/<store>/<SKU>` redirects and unknown links 404.
- [ ] Alerts reach Telegram (down, missed heartbeat, backup failure).
- [ ] A restore test restores the newest production dump.
- [ ] Dokploy dashboard `:3000` confirmed closed from outside.
- [ ] All of this before 26 December 2026.
