# Every API error is an RFC 9457 problem details response

All API errors, including validation errors and domain exceptions mapped by the exception handler, are returned as RFC 9457 problem details (`type`, `title`, `status`, `detail`) with an extra stable `code` that clients branch on. The format is fixed in Phase 2, before any client exists, because the generated api-client, the storefront and the mobile app all depend on it and changing it later is a breaking change for every consumer.
