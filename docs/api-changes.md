# API changes

Breaking changes to the HTTP API, newest first. The generated OpenAPI schema in
`packages/api-client/openapi.json` is the reference for the current contract.

## `GET /api/v1/staff/me/` removed

The store-scoped endpoint is gone. Clients that read a user's role and permissions
for one store must call the global `GET /api/v1/me/` instead, which needs no
`X-Store` header. It returns:

- `user`: the signed-in user's `id` and `email`.
- `memberships`: every store where the user has an active membership, each with
  the store's `slug`, `name` and `accent_color`, the `role`, and the role's
  `permissions` sorted alphabetically.

Inactive memberships, inactive users and inactive stores are excluded. A platform
operator without a membership gets an empty `memberships` list. This is the
`GET /api/v1/me/` endpoint described in ADR-0026.
