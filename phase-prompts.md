# Phase prompts — commerce-platform

How to use each phase prompt with OpenCode (model: DeepSeek):

1. Paste the phase prompt and run `/grill-with-docs` on it until the open questions are settled.
2. Run `/to-spec` to turn the agreed result into a spec, then `/to-tickets` to split it.
3. Work ticket by ticket with `/implement`, review each diff with `/code-review`.
4. Close the phase with `/retro` and update `AGENTS.md` with anything learned.

Do not start a phase until the previous one meets its "Done when" criteria.

---

## AGENTS.md

The project instructions live in `AGENTS.md` at the repo root. Every phase prompt starts by reading it.

---

## Phase 0 — Planning

Run this phase in Claude Code (critical phase).

```
We are starting commerce-platform. Read AGENTS.md, ROADMAP.md and docs/agents/.

Decisions ALREADY TAKEN (do not reopen them; record each one as an ADR in docs/adr/):
1. One business today, SaaS later. Our own stores are the first rollout ring;
   new optional features ship behind per-store feature flags. The SaaS isolation model is
   decided later, with real usage data.
2. Stores are data (created with a create_store command), N stores supported.
   Every business table belongs to a Store.
3. Inventory is per store, addressed by Location (StockItem = variant + location).
   Transfers between stores are an outbound and an inbound movement.
4. Python 3.12 and Django 5.2 LTS, Django REST Framework as a thin layer.
5. Modular monolith; clean architecture only in modules with business rules
   (inventory, orders, payments, agents).
6. Development workflow: OpenCode with DeepSeek, Matt Pocock skills in the repo,
   AGENTS.md as the single source of instructions; Claude Code plans critical
   phases and reviews PRs. No Gentle-AI SDD/ODD flows in this repo.
7. GitHub Issues as the tracker.
8. One themed Next.js storefront resolved by domain (not one app per store).
9. Ghosty Teams is a replaceable interface for @mentions; agent handles live in
   our AgentDefinition model.
10. Deploy: backend on a VPS with Dokploy, storefront on Vercel.

Run /wayfinder over the whole platform. The scope, in delivery order (see ROADMAP.md):
0. Planning
1. Skeleton: monorepo, Docker for PostgreSQL and Redis, Django with a custom User.
2. API foundation: DRF config, X-Store resolution, tests and CI.
3. Stores, per-store feature flags and store-scoped RBAC.
4. Catalog: categories, products, variants with SKU, media.
5. Inventory (locations) and orders with clean architecture.
6. Payments (Mercado Pago with OXXO) and deployment with Dokploy.
7. Themed storefront, first live with the home store.
8. Second store and channels: TikTok Shop sync, catalog feeds, conversion events.
9. Agent platform and Instagram publishing agent.
10. WhatsApp sales agent with human handoff.
11. Customer follow-up agent.
12. Bundle suggestions.
13. Observability and hardening.
14. Mobile app with QR scanning and favorites.

I want a map of the decisions still OPEN, ordered by which phase they block.
Focus on phases 1 to 3; later phases only need their open questions listed.

Then run /grill-with-docs on the architecture so the domain vocabulary ends up in
GLOSSARY.md and the decisions above are recorded as ADRs.
Finally, run /to-spec and /to-tickets for Phase 1 only.
```

**Done when:** `GLOSSARY.md` and the ADRs exist, the open questions are listed per phase, and Phase 1 has tickets in GitHub Issues.

---

## Phase 1 — Skeleton

```
Phase 1 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: a runnable skeleton.
- Monorepo root with .gitignore (Python, Node, env files, OS files) and README.md.
- docker-compose.yml with postgres:16 (db/user/password: shop) and redis:7, with a
  named volume for PostgreSQL data.
- backend/ managed with uv (Python 3.12, pyproject.toml and a committed uv.lock), Django
  project in `config/`, modules in `apps/`.
- Settings read from backend/.env with django-environ; commit backend/.env.example.
- apps/accounts with a custom User model (email as USERNAME_FIELD) created BEFORE the
  first migration, registered in the admin.
- Dependencies in pyproject.toml: django>=5.2,<5.3 (LTS), djangorestframework, djangorestframework-simplejwt,
  drf-spectacular, django-filter, django-environ, psycopg[binary], celery, redis,
  pytest, pytest-django, factory-boy.

Do not add any other module yet.
```

**Done when:** you log into `/admin/` with your email and the first commit is made.

---

## Phase 2 — API foundation

```
Phase 2 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: the base every endpoint will build on.
- DRF settings: JWT auth (simplejwt), URL versioning under /api/v1/, default page-number
  pagination, django-filter backend, IsAuthenticated by default.
- A domain exception handler in config/exceptions.py that maps domain exceptions to HTTP
  status codes in one place (start with PermissionDenied -> 403 and NotFound -> 404).
  Every error response is RFC 9457 problem details (type, title, status, detail) plus a
  stable `code`.
  Shared domain exceptions live in apps/shared/domain/exceptions.py.
- OpenAPI schema and docs with drf-spectacular at /api/v1/schema/ and /api/v1/docs/.
- Health endpoints at /api/v1/health/live/ (liveness, no dependency checks) and
  /api/v1/health/ready/ (readiness, checks PostgreSQL and Redis), both public.
- Middleware that reads the X-Store header into `request.store_slug`; it never resolves
  `request.store`. Store-scoped views opt in through a shared mixin (not a permission
  class) that resolves the store after authentication and permissions; the Store model
  arrives in Phase 3, so design the resolver to be swapped later.
  Endpoints are global by default (health, auth, docs); store-scoped views opt in, and
  only they reject a missing X-Store with 400 (`store_header_missing`); a malformed slug
  is rejected with 400 (`store_header_invalid`).
- pytest configured with pytest-django; tests/unit and tests/api folders; one test per item.
- Ruff for linting and formatting, with a pre-commit hook.
- GitHub Actions workflow that runs ruff and pytest on every pull request, with a
  PostgreSQL service container.
```

**Done when:** `/api/v1/docs/` opens, the tests pass and CI is green on a PR.

---

## Phase 3 — Stores and RBAC

```
Phase 3 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: stores and store-scoped role-based access control.
- apps/stores: Store (slug unique, name, domain) and a `create_store` management command.
  The `anime` and `home` stores are created with that command, never with a migration.
- Per-store feature flags: StoreFeatureFlag (store, code, enabled, unique store+code) and a
  service to ask whether a flag is on for a store. No third-party flag library.
- Update the X-Store middleware to load the Store; unknown or missing store returns 400
  for store-scoped endpoints.
- In apps/accounts: Permission (code unique, description), Role (name unique,
  permissions M2M), StoreMembership (user, store, role, is_active, unique user+store).
- Customers have no membership; only staff do.
- Seed roles with a data migration: owner, store_admin, content_editor, warehouse, support.
  Seed the first permission codes needed by later phases (orders.place_manual,
  orders.refund, inventory.adjust, catalog.manage, social.approve_post).
- An Authorizer port in apps/shared/domain/ports.py with `require(user, store, permission)`
  and a MembershipAuthorizer implementation that raises PermissionDenied.
- A DRF permission class IsStoreStaff as a first barrier.
- Admin screens for roles and memberships.
- Unit tests for MembershipAuthorizer and API tests proving a user with a role in one
  store cannot act on the other store.
```

**Done when:** the cross-store permission tests pass.

---

## Phase 4 — Catalog

```
Phase 4 of commerce-platform. Read AGENTS.md, GLOSSARY.md, ADR-0023 and ADR-0024.

Goal: the product catalog, managed by the platform operator in the admin, loaded in bulk
with import_catalog, and readable through the API.
- apps/catalog (plain Django, no clean architecture). Every model belongs to a store,
  directly or through its parent; nothing is deleted except the ProductMedia link
  (is_active, PROTECT foreign keys).
  - Supplier: store, name, is_active.
  - Design: store, number (unique per store, assigned in order on creation, never edited
    or reused, shown as 5 digits), name, supplier, supplier_design_name (unique per
    supplier).
  - Category (flat, no parent): store, name, slug (unique per store), sku_code, shape
    (rectangle or contour), attribute and option schema in our own format (ADR-0024; size
    values carry width_cm and height_cm), is_active. A schema edit that would invalidate
    an active product, or remove or rename an option value code in use, is rejected.
  - Product: store, category, design, name (category name + design name by default),
    slug (unique per store, generated without accents, editable), description,
    attributes, is_active, timestamps. Category and design are read-only once it has
    variants.
  - ProductVariant: product, store (denormalized, must match), sku, option values,
    price, compare_at_price, cost, weight_grams, package_length_cm, package_width_cm,
    package_height_cm (shipping fields optional until Phase 6b), is_active.
    SKU = <category sku_code>-<design number>-<option value codes> (FRZ-00012-MAT,
    ALM-00012-FIG-80), generated on creation, unique per store ignoring case (stored
    uppercase), never changed or reused; typed by hand only for a product without a
    design. Option values are read-only once created. Stock is NOT here (Phase 5).
  - Prices (ADR-0023): MXN, 2 decimals; price > 0 and compare_at_price empty or greater,
    both with IVA; cost >= 0, required, without IVA. One validator used by the admin and
    both commands.
  - Collection: store, name, slug (unique per store), description, supplier (optional),
    is_active, ordered products (a product may be in several or none).
  - Media: store, storage_key (stores/<store_id>/media/<sha256>.<ext>, content hash unique
    per store), mime_type, alt_text, width, height (read with Pillow), metadata.
    JPEG, PNG or WebP up to 10 MB.
  - ProductMedia: product, variant (nullable), media of the same store, role (main or
    gallery), position; at most one main image per product (conditional unique
    constraint).
- File storage through django-storages: Cloudflare R2 in staging and production (bucket
  credentials from the environment; public product media only, served from our own
  media domain), local filesystem in development. Build public URLs from storage_key and
  MEDIA_BASE_URL. Content-addressed files get long-lived cache headers.
- Admin with inlines for variants and media; platform operator only (ADR-0012).
- import_catalog --store <slug> --csv <file> [--images <dir>] --operator <email>
  [--dry-run]: one row per variant; categories and suppliers must already exist (an
  unknown one rejects the row), collections are created if missing and the dry-run
  report lists every one it would create; designs matched by (supplier,
  supplier_design_name) and numbered in order of first appearance; variants matched by
  SKU; validates every row first, then writes all or nothing; never deactivates rows
  missing from the file; images optional, deduplicated by content hash. Ship a template
  spreadsheet for the CSV.
- set_prices --store <slug> --category <slug> [--option-value <code>] --price X
  [--compare-at-price Y | --clear-compare-at-price] [--cost Z] --operator <email>
  [--dry-run]: updates every variant of that category and size, active and inactive, in
  one transaction; the report counts active and inactive variants separately and those
  already at those prices.
- Both commands require an active superuser as --operator and write one admin LogEntry
  per changed variant with old and new values; --dry-run writes nothing.
- Public read-only endpoints, anonymous and store-scoped, filtered by request.store:
  list categories, list collections, list products (filter by category or collection,
  search by product name ignoring case and accents with PostgreSQL unaccent), product
  detail by slug, variant lookup by SKU (for the future QR feature). A product is
  visible when it, its category and at least one variant are active; it may have no
  image yet. Products are listed newest first, or in the collection's order when
  filtered by collection. Never expose cost, the supplier or the supplier design name.
  Enabling unaccent needs a database role allowed to run CREATE EXTENSION; production
  (Phase 6) must grant it.
- API tests proving a product from one store never appears in the other.
```

**Done when:** the real catalog is loaded with `import_catalog` and the API returns it only for `home` (images come in Phase 4b).

---

## Phase 4b — Catalog photos

```
Phase 4b of commerce-platform. Read AGENTS.md, GLOSSARY.md, ADR-0026, ADR-0027 and ADR-0028.

Goal: staff turn one or more phone photos of products into catalog images.

- New clean-architecture module apps/photos: Photo submission state machine, idempotency,
  quad and crop validation, Authorizer calls. It never writes catalog models; it creates
  Media and product images through the catalog service seam.
- Private original storage (R2 in staging and production, MinIO in local and level 2) and
  a MediaUploader port. API multipart now; presigned direct-to-R2 uploads are deferred to
  the video phase.
- Upload normalizes the file: HEIC decoded with pillow-heif, EXIF orientation applied,
  metadata stripped, JPEG. It enforces 25 MB and 50 MP, stores the original in the
  private bucket and generates one downscaled private preview served by an authorized
  endpoint.
- Staff endpoints guarded by catalog.manage through the Authorizer: upload with an
  Idempotency-Key, submission status and preview, apply, retry, redo and discard.
- Celery processing: rectangle photos are straightened from four staff-tapped corners
  and cropped to the photographed size's ratio; rectangle categories without dimensions
  keep the quad's ratio; contour products use a shared draggable crop frame with the
  size's ratio and fall back to 4:5; group photos are always 4:5 and link one Media as a
  gallery image to many products.
- No ML in Phase 4b: no background removal. Light correction is deterministic gray-world
  white balance with capped gains and a small autocontrast cutoff, staff can switch it
  off, and pipeline_version records the result. Renditions are 320/800 WebP with keys
  derived from the Media storage key.
- ProductMedia gains is_active; one active main per product; (product, media) unique;
  links are deactivated, reactivated and upserted without losing position; product
  readers return active links only.
- Quetzal shell: sign-in behind the BFF session (ADR-0027), store in the URL,
  permission-driven menu, light/dark/system theme and Store.accent_color;
  GET /api/v1/me/; packages/api-client generated with orval.
- Prerequisite (human pull request): web/console/scripts/check.sh, the factory running
  the check of every area a ticket touches, the level-2 E2E job, and the sudoers entry.
```

**Done when:** a staff member photographs a blanket on their phone and it becomes that product's main image, and a group photo is linked to several products. Video is Phase 4d.

---

## Phase 4d — Catalog video

```
Phase 4d of commerce-platform. Read AGENTS.md, GLOSSARY.md and ADR-0028.

Goal: staff add a short product video without changing the callers built in Phase 4b.

- Switch the MediaUploader port to presigned direct-to-R2 uploads, the path ADR-0028
  deferred; keep the API multipart adapter for still photos.
- Validate duration, codec and size; generate the video renditions the public product API
  exposes (the storefront uses them in Phase 7).
- Do not add video fields to the Phase 4b models. The decoding and playback design is
  decided in this phase's /grill-with-docs.
- Quetzal page for uploading the video and playing it back.
```

**Done when:** a short video uploaded from Quetzal plays back in Quetzal, and the public product API returns its URL; the storefront shows it in Phase 7.

---

## Phase 5 — Inventory and orders

```
Phase 5 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: the first clean architecture modules. Use /tdd: every use case starts with a
failing unit test using fake ports.

apps/inventory
- domain: StockLevel and movement rules, OutOfStock exception.
- application: ReserveStock, ReleaseStock, AdjustStock (requires inventory.adjust).
- infrastructure: Location (store, name, is_active), StockItem (variant, location,
  quantity, unique variant+location) and InventoryMovement (variant, location,
  quantity +/-, reason: purchase, sale, return, adjustment, transfer; order nullable;
  note; created_at). Each store starts with exactly one location; inventory is per
  store, but stock is always addressed by location so a shared location can be added
  later as a data change. A transfer between stores is an outbound and an inbound
  movement with reason=transfer. Reservation must lock the row (select_for_update)
  to avoid overselling under concurrency.
- Exposed to other modules through a StockService port.

apps/orders
- domain: Order and OrderItem entities, status transitions (pending, paid, shipped,
  delivered, cancelled, refunded) with InvalidTransition, total calculation.
- application: PlaceOrder (reserves stock through StockService, snapshots sku, name,
  unit_price and unit_cost into each item, computes totals), CancelOrder (releases stock).
- infrastructure: Order (UUID id, human number like AN-000123 per store, store, customer,
  channel: web, app, tiktok, whatsapp, in_person; external_id unique per channel when present,
  status, currency MXN, subtotal, discount_total, shipping_total, tax_total, total,
  shipping_address JSON, placed_at) and OrderItem, with DjangoOrderRepository.
- interfaces: POST /api/v1/orders/ (customer), GET own orders, staff endpoints for
  status changes guarded by the Authorizer.
- PlaceOrder runs in one database transaction: all or nothing.
- Map OutOfStock and InvalidTransition to 409 in the domain exception handler.

Analytics readiness (issue #1, analytics): later reports read orders directly, so from
this phase on:
- Every order records its sales channel (storefront, WhatsApp, TikTok Shop, in person).
- Every order item snapshots price, cost and product data at sale time; reports never
  join back to the current catalog for them.
- Every business row has created_at in UTC; reports group by the store's timezone.
- TikTok Shop orders (Phase 8) are stored as our own orders, so analytics reads one
  source.

Open for the grilling (issue #1): selling a variant with zero stock when it is made to
order from its supplier (Phase 5b builds purchasing on top), the supplier's availability
per variant, and Store.timezone.

When finished, propose a project skill `new-domain-module` in .claude/skills/ based on
how apps/orders was built (use /writing-for-agents).
```

**Done when:** placing an order reduces stock atomically, ordering more than available of a variant sold from stock returns 409 (selling a made-to-order variant with zero stock is decided in the Phase 5 grilling), and the unit tests run without a database.

---

## Phase 5b — Purchasing and restocking

```
Phase 5b of commerce-platform. Read AGENTS.md, GLOSSARY.md and issue #1 (purchasing and
restocking).

Goal: buy from suppliers on a weekly restock cycle without losing track of what was sold
before it was in stock.
- A module with business rules (clean architecture): purchase list (sold-but-not-in-stock
  variants and items added by hand), purchase orders (draft, sent, partially received,
  received, cancelled), receipts that create inbound stock movements for what arrived.
- A supplier's weekly restock schedule, closed days and extra visits; order cutoff and
  the promised date computed in the store's timezone.
- A scheduled task that drafts the purchase order the day before each restock; restock
  suggestions from recent sales.
- Customer orders waiting for an item that did not arrive are flagged.
```

**Done when:** a sale of an out-of-stock variant appears on the purchase list, goes into a purchase order, and a partial receipt adds the received quantity to stock.

---

## Phase 6 — Payments and deployment

```
Phase 6 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: take real payments and run in staging and production.

apps/payments (clean architecture)
- A PaymentGateway port with a Mercado Pago implementation (cards and OXXO).
- Payment: order, provider, provider_ref, amount, status, timestamps.
- Use cases: CreatePayment (returns what the frontend needs to start checkout) and
  HandlePaymentWebhook (verifies the signature, is idempotent by provider_ref, moves the
  order to paid through the orders module, never by writing Order directly).
- Celery: app setup in config/celery.py, a task that sends the order confirmation email.

Deployment
- backend/Dockerfile (Python 3.12 slim, gunicorn), with migrate run before the app starts.
- docker-compose.prod.yml with api, worker, beat (same image, different commands),
  postgres and redis.
- GitHub Actions on merge to main: tests, build the image, push to GHCR, call the
  Dokploy API to deploy to staging. A version tag deploys to production.
- Two environments with separate databases and separate Mercado Pago credentials
  (test mode in staging).
- Document in docs/deployment.md: server hardening checklist, Dokploy setup, database
  backups to external S3-compatible storage, domain and SSL.
- Basic error tracking and structured logging from day one.
```

**Done when:** a test payment in staging marks the order as paid and sends the email.
**Also start now:** the Meta and TikTok developer app reviews needed in Phase 9.

---

## Phase 6b — Shipping

```
Phase 6b of commerce-platform. Read AGENTS.md, GLOSSARY.md and issue #1 (shipping).

Goal: quote and ship every non-TikTok order through Envíosperros.
- A ShippingProvider port with an Envíosperros implementation (API v3: rates, labels,
  label download, pickup); staging only in development and tests.
- The Envíosperros token is a per-store integration credential (ADR-0020).
- The sales channel decides the carrier: TikTok Shop orders ship with TikTok's
  logistics; every other order through Envíosperros.
- A per-shipment drop-off surcharge, a per-store setting (10 MXN for home today), added
  to the quote shown to the customer, never to a variant's cost.
- Variant weight and package dimensions become required to quote.
```

**Done when:** a staging order gets a quote, a label is created and downloaded, and the price shown includes the surcharge.

---

## Phase 7 — Storefront, first live with home

```
Phase 7 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: the blankets store live at its own domain.
- packages/api-client: TypeScript client generated from /api/v1/schema/, regenerated by
  a script; the storefront and the mobile app will use it.
- web/storefront/: one Next.js app with TypeScript and the App Router for every store. It
  resolves the store and its theme from the request domain and sends it as X-Store.
  It goes live with the home store first.
- Pages: home, category listing, product detail (variants: size and color), cart,
  checkout with Mercado Pago, order confirmation, customer login and order history.
- Product detail shows the public video URL returned by the API since Phase 4d, with
  playback controls and a poster image.
- Product and category pages rendered on the server for SEO, with metadata, Open Graph
  and a sitemap. Images through next/image.
- Mobile-first layout: most buyers arrive from TikTok and Instagram on their phones.
- Deployed on Vercel with a preview per pull request; CI runs lint, type check and build.
- Product analytics (issue #1, analytics): storefront events (views, cart, funnel,
  traffic sources) go to a dedicated tool such as PostHog, never into our PostgreSQL,
  because event volume grows fast. Business analytics stays in PostgreSQL.
```

**Done when:** someone buys a blanket on your domain.

---

## Phase 8 — Second store and sales channels

```
Phase 8 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: the anime store and the external channels.
- The anime store on the same storefront: its domain and its theme, no new app.
- apps/integrations:
  - TikTok Shop: a Celery Beat task that imports TikTok orders as Order with
    channel=tiktok (idempotent by external_id) and pushes stock levels to TikTok.
    Wrap the TikTok API behind a port so it can be faked in tests.
  - Catalog feed endpoints per store for Meta and TikTok catalogs.
  - A collection's catalog PDF generated from its products.
  - Server-side conversion events (Meta Conversions API, TikTok Events API) sent by Celery
    when an order is paid.
- Storefront pixels per store; UTM parameters stored on the order.
- Analytics readiness (issue #1, analytics), as in Phase 5: every order records its
  sales channel (storefront, WhatsApp, TikTok Shop, in person); every order item
  snapshots price, cost and product data at sale time; every business row has
  created_at in UTC and reports use the store's timezone; TikTok Shop orders are stored
  as our own orders, so analytics reads one source.
```

**Done when:** a sale on TikTok Shop reduces stock in the platform and appears as an order.

---

## Phase 9 — Social media agents

```
Phase 9 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: scheduled, validated and approved social media posts.
- apps/social: SocialAccount (credentials read through the CredentialStore port,
  ADR-0020; never a token on the model),
  PostingSchedule, Post (status machine: planned, generating, validating, needs_review,
  approved, rejected, publishing, published, failed), PostTarget (one per account,
  external_post_id prevents double publishing), PostMedia, PostMetrics.
- apps/agents (clean architecture):
  - An LLMClient port with Claude and DeepSeek implementations.
  - Versioned prompt templates in code (PROMPT_VERSION), filled with product data,
    store tone and per-platform rules. No agent writes prompts for another agent.
  - Generator use case: one caption per platform.
  - Validator use case: code checks first (length per platform, hashtag count, price
    matches the database, no licensed franchise or character names), then an LLM judge
    for tone. Returns a ValidationResult with each check.
  - Every LLM call recorded in AgentRun (model, prompt_version, tokens, latency, status).
  - Video script use case: recommends product bundles and writes recording scripts
    (shots, duration, hook, on-screen text) in the style of the reference videos. The
    staff records the videos and uploads them through Quetzal (Phase 4d); there is no
    AI-generated video. The bundle recommendation logic is shared with Phase 12
    (suggested bundles); design it once.
- Celery Beat creates posts from schedules; rejected posts regenerate at most twice,
  then go to needs_review. Add a social.propose_post permission for content_editor
  (a new data migration, ADR-0021); approval requires social.approve_post, so posts
  proposed by content_editor need approval from owner or store_admin.
  Open question for the grilling: should a per-person four-eyes rule also apply
  (nobody approves a post they proposed), and what happens in a store with a
  single owner?
- Publishers for Meta Graph API and TikTok Content Posting API behind ports.
- evals/: dataset, graders (code and model based) and a runner; a GitHub Actions job runs
  it when prompts change and fails below the threshold.
```

**Done when:** a post is generated, passes validation, you approve it and it appears on Instagram.

---

## Phase 10 — Observability and hardening

```
Phase 10 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: see what the system does and make it harder to break.
- OpenTelemetry for Django, Celery and the LLM clients, exported to a collector with
  Prometheus and Grafana. Dashboards: requests, errors, latency, orders per store,
  LLM tokens and cost per agent and prompt version.
- Throttling on public and auth endpoints.
- Security review: settings for production, CORS, headers, secrets handling, dependency
  audit, admin access restricted.
- Restore test: restore a database backup into staging and verify it works.
```

**Done when:** the dashboards show real traffic and a backup has been restored successfully.

---

## Phase 11 — Mobile app

```
Phase 11 of commerce-platform. Read AGENTS.md and GLOSSARY.md.

Goal: a customer app for both stores.
- mobile/: React Native with Expo and TypeScript, using packages/api-client.
- QR scanning: product labels contain a URL like https://<store-domain>/p/<SKU>.
  Universal links (iOS) and app links (Android) open the product in the app when
  installed and on the web otherwise. Prices are always fetched live.
- Favorites: Favorite model (user, product, unique) in the backend, endpoints to add,
  remove and list; visible on web and mobile.
- Login with JWT, tokens in secure storage.
- EAS Build for store releases on a version tag, EAS Update for JavaScript-only fixes.
```

**Done when:** scanning a product label opens it in the app with its current price.