---
status: accepted
---

# Staff work happens in Quetzal, a mobile-first Next.js console separate from the storefront

Quetzal is the staff console: the one place where staff of every store do their work (catalog photos first, then orders, shipping and the handoff inbox). It is a Next.js app (App Router, TypeScript) in `web/console/`, separate from the storefront, and it talks to the backend only through the generated `packages/api-client`. The Django admin stays a platform-operator tool: it is global and ignores per-store roles, so it can never serve staff or, later, other businesses. Quetzal is mobile-first (responsive web, not a native app), because its first screens are used with a phone in the warehouse.

The store is part of the URL (`/<store-slug>/photos`), and the console turns that segment into the `X-Store` header; the store switcher only changes that segment. Only users with at least one active store membership can sign in; a platform operator without a membership sees no stores and uses the Django admin. `GET /api/v1/me/` returns the user and, for each membership, the store's slug, name, accent color and the user's permissions there. Navigation is driven by permissions, never by role names, and the backend re-checks every action through the Authorizer: hiding a button is not authorization.

Sessions follow ADR-0027: the JWT lives in an httpOnly cookie behind the console's Next.js server, and the browser reaches the API through one proxy route.

## Stack and structure

- Tailwind with themes through `@theme` CSS variables, and shadcn/ui components. The base theme (light and dark) is designed with tweakcn and committed as CSS.
- Each user picks light, dark or system. Each store has an `accent_color` (validated hex) stored on `Store` and editable in the Django admin; the console paints its accent with it so staff can see at a glance which store they are in. A full per-store theme is a storefront concern, decided in Phase 7.
- `packages/api-client` is generated from the OpenAPI schema with orval: TanStack Query hooks over axios, one per endpoint.
- TanStack Query owns all server state and it is never copied into Zustand. Zustand holds UI state only (corner positions, upload progress, menus, the chosen theme), and never tokens or session data.
- Atomic design, split by feature. Shared pieces live in `src/components/{atoms,molecules,templates}` (shadcn installs into `atoms/`); each feature owns `src/features/<feature>/{molecules,organisms,hooks,stores}` (`photos`, `orders`, `shipping`, `handoff`); routes in `src/app/[store]/...` only compose a feature's organisms. A feature never imports another feature; a piece two features need moves to `src/components/`.
- UI text is Spanish, kept in `next-intl` message files from the start, never inline. Code stays in English.
- pnpm workspaces at the repo root hold `web/console`, `web/storefront` and `packages/api-client`.

## Testing

- Vitest and Testing Library for components and hooks; MSW with orval-generated mocks for the API.
- Level 1: Playwright flows per feature in a phone viewport against the mocked API, on every pull request and in the night factory, with screenshots attached to the pull request.
- Level 2: a few critical Playwright flows end to end against the real stack (Django, Celery, PostgreSQL, Redis and MinIO in place of R2, seeded with `seed_demo`), run only in GitHub Actions as a required check when a pull request touches `web/console/`, `packages/` or `backend/`. The night factory never runs it, because it would need Docker for the agent user.

## Deployment

Quetzal is deployed with Dokploy on the VPS, next to the backend, on its own subdomain (such as `consola.<domain>`) with `noindex`. Its users are a few staff members, so it needs no CDN, and its server-side proxy reaches Django locally. Dokploy preview deployments give each pull request its own URL. This amends ADR-0010 for the console only; the storefront still goes to Vercel (Pro plan, since Hobby forbids commercial use) from Phase 7. Nothing is deployed or paid for until Phase 6 brings a staging API.

## Considered Options

- Staff pages in the Django admin: rejected, because the admin is global, ignores per-store roles and cannot serve other businesses.
- Staff routes inside the storefront: rejected, because it mixes customer and staff sessions, permissions and release cadence in one app.
- Django-rendered pages (HTMX): rejected, because the photo page needs rich touch interaction (dragging four corners) and the API should be the single source for web and mobile.
- A native app: rejected; the phone browser is enough, including the camera.
- Quetzal on Vercel: rejected for now; it would cost the Pro plan for an internal tool with little traffic, and Dokploy already offers pull-request previews.

## Consequences

- The first delivery is the shell (sign-in, store in the URL, permission-driven menu) plus the Phase 4b photo page; products and categories keep being edited in the Django admin until a later phase needs staff to do it.
- New backend work: `Store.accent_color` (a migration in `stores`, human-reviewed), `GET /api/v1/me/`, and refresh-token rotation (ADR-0027).
- Before the night factory takes console tickets, a human pull request adds `web/console/scripts/check.sh` (lint, typecheck, unit and level-1 tests), teaches the factory to run the check of every area a ticket touched, and adds that script to the documented sudoers rule; `tools/factory/` and `.github/` are protected paths.
- The level-2 end-to-end job lives in `.github/workflows/`, so a human writes it.
- The photo pipeline itself (HEIC conversion, direct or proxied upload, corner math, Celery processing) is decided in the Phase 4b grilling, not here.
