# Every API error is an RFC 9457 problem details response

All API errors, including validation errors and domain exceptions mapped by the exception handler, are returned as RFC 9457 problem details (`type`, `title`, `status`, `detail`) with an extra stable `code` that clients branch on. The format is fixed in Phase 2, before any client exists, because the generated api-client, the storefront and the mobile app all depend on it and changing it later is a breaking change for every consumer.

## Published codes

These are the problem codes published in Phase 2. Clients branch on the `code`, not on the status or the detail text; a code can only be added, never renamed.

| Code | Status |
| --- | --- |
| `validation_error` | 400 |
| `parse_error` | 400 |
| `not_authenticated` | 401 |
| `token_invalid` | 401 |
| `invalid_credentials` | 401 |
| `permission_denied` | 403 |
| `not_found` | 404 |
| `method_not_allowed` | 405 |
| `not_acceptable` | 406 |
| `unsupported_media_type` | 415 |
| `throttled` | 429 |
| `store_header_missing` | 400 |
| `store_header_invalid` | 400 |
| `service_unavailable` | 503 |
| `internal_error` | 500 |
