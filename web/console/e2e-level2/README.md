# Level 2 end-to-end tests

These flows run against the real stack (Django, Celery, PostgreSQL and Redis)
in the `Level 2 E2E` GitHub Actions job. They are never part of level 1:
`playwright.config.ts` and `scripts/check.sh` only pick up `e2e/`.

The stack is seeded with the `e2e_seed` management command. The job starts the
API and the console itself, so there is no `webServer` entry in
`playwright.level2.config.ts`.

C1 (#97) adds the sign-in flow and C6 (#102) the photo flow here. Until then,
these are the smoke tests that prove the console and the API are reachable.
