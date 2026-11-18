# REVIEW.md

Rules for any agent reviewing a pull request in this repo. AGENTS.md has the conventions;
this file says where changes here actually break and how to report it. Load it from `main`,
never from the branch under review.

Every rule below came from an owner review on at least two pull requests. Apply every
rule whose trigger matches the diff; skip the rest.

## What failure looks like here

- **Partial state**: two writes where the first commits and the second can fail.
- **Store leak**: one store's data, file or cache entry reachable from another store.
- **Broken contract**: two pull requests or modules disagree on a name, a state or a
  signature, and both pass CI on their own.
- **Late rejection**: the server does expensive or private work before it authorizes or
  validates the request.

## Rules

### 1. Multi-step writes commit together
- **Trigger**: a use case or task writes through two ports (catalog link + repository save,
  file upload + database row, database write + Celery enqueue).
- **Check**: the writes run inside one unit-of-work port (Django adapter with
  `transaction.atomic()`, fake in unit tests), or the losing path cleans up what it wrote
  (orphaned files). Celery enqueues go through `transaction.on_commit`. A unit test makes
  the second write raise and asserts the rollback.
- **From**: #127 (orphaned private files on a double tap), #131 (apply without a
  transaction), #132 (enqueue without `on_commit`).

### 2. Contracts match across open pull requests
- **Trigger**: the diff defines or consumes a Celery task name, a port signature, an
  entity state transition, or a generated file (`openapi.json`, the API client).
- **Check**: the diff matches `docs/contracts/<module>.md`, or updates it along with every
  consumer. Search open pull requests and tickets for the same name. Producer and consumer
  agree on the exact task name (set `name=` explicitly), the state the consumer receives,
  and a single port and adapter. Generated files are regenerated after a merge
  (`dump_openapi`, `pnpm generate:client`), never hand-merged.
- **From**: #119 (`openapi.json` conflict), #131 + #132 (task name, entry state and
  duplicate queue port).

### 3. State machines hold for every entry path
- **Trigger**: a domain entity gains a status, a transition or a counter (`attempts`,
  `version`).
- **Check**: list every path that reaches each state (upload, retry, redo, discard, worker).
  Each path increments counters the same way, `MAX_*` limits hold on all of them, and the
  consumer accepts every state a producer can hand it. An action during a non-final state
  (discard while `processing`) is either rejected with a stable `code` or handled by the
  consumer as a deterministic failure.
- **From**: #131 (redo skips `attempts`, discard during `processing`), #132
  (`start_processing()` on an already-processing submission).

### 4. Store isolation reaches caches and storage keys
- **Trigger**: a store-scoped endpoint, query, client cache key, storage key, or a console
  route that carries an id.
- **Check**: the store is part of the cache key and the storage key prefix
  (`stores/{id}/`). Readers verify the prefix and fail closed. The console takes the store
  from route params, not `window.location`. A test proves one store's data never appears
  in another.
- **From**: #127 (private reader ignores `store`), #128 (query keys without the store,
  stale `X-Store`, ids kept across a store switch).

### 5. Authorize and validate before the work
- **Trigger**: an endpoint that reads an upload, streams a private file, or exposes a page
  or admin screen tied to a permission.
- **Check**: size, idempotency key and permission are checked before the body is read or
  processed. Private responses send `Cache-Control: private, no-store`. Console pages render
  a "no permission" state from `membership.permissions`, not only a hidden menu item.
  Admin models that grant roles are superuser-only.
- **From**: #30 (`StoreMembership` editable by staff), #127 (file read before the 403,
  preview without cache headers), #128 (pages reachable by URL).

### 6. Serializers validate shape, including JSON fields
- **Trigger**: a `JSONField`, `DictField`, free-form string or URL-like field in a
  serializer or model.
- **Check**: the shape is validated at the boundary (nested serializer, fixed list
  length, hostname format), with an API test where a malformed body returns 400
  `validation_error`. Rules that need the image or the database stay in the use case.
- **From**: #31 (`Store.domain` accepts any string), #127 + #131 (`corners`/`crop` accept
  any JSON).

### 7. Identifiers in use stay immutable
- **Trigger**: a field that is part of a generated identifier (SKU codes, option value
  codes, slugs) becomes editable, or an API error `code` is renamed.
- **Check**: changing an identifier is rejected once anything references it, with a test.
  A renamed error `code` is a contract change: every caller (console, docs, client) is
  updated in the same pull request.
- **From**: #52 (`Category.sku_code` editable after variants exist), #127 (error code
  rename).

## Reporting

- Open with one line: how many findings and whether any blocks the merge. When nothing
  needs fixing, say so plainly.
- Tag each finding **Important**, **Nit** or **Pre-existing**. Only Important findings
  block. Pre-existing bugs go to a follow-up issue, not to the author.
- Every finding names the file and line, and gives the concrete failure case (inputs or
  sequence → wrong result). A finding without a failure case is a question; ask it as one.
- Important findings come as checkbox acceptance criteria, including the tests that prove
  the fix and `./scripts/check.sh` for each touched area.
- When a finding is a mistake a lint rule, architecture check or test could catch, name
  that guard in the finding, so the next agent fails the check instead of repeating the
  mistake. A reviewer that can open issues opens a follow-up for the guard; otherwise the
  owner does.
- State the scope: what this pull request must fix, and what is tracked elsewhere (issue
  number).
- At most three Nits per review.
- Agents never approve. End with: "Approval stays with the owner."
