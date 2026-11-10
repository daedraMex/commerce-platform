---
status: accepted
---

# Web apps keep the JWT in an httpOnly cookie behind their own Next.js server

Every web app (the Quetzal staff console and the storefront) keeps the API's JWT pair in httpOnly, `Secure`, `SameSite=Lax` cookies set by its own Next.js server, acting as a backend-for-frontend. Browser JavaScript never sees a token. The browser calls one proxy route of its own app (such as `/api/backend/...`); the server attaches the access token from the cookie, forwards the call to Django and refreshes the token when it expires. The proxy accepts only requests that carry a custom header (such as `X-Requested-With`), which the app's axios instance always sends, as CSRF protection on top of `SameSite=Lax`. Cookies are scoped to the app's own domain, so a staff session and a customer session never share a cookie.

Refresh tokens rotate and the used one is blacklisted (`ROTATE_REFRESH_TOKENS` and `BLACKLIST_AFTER_ROTATION` with simplejwt's `token_blacklist` app), so signing out or replacing a stolen token really invalidates it.

## Considered Options

- Tokens in browser memory or `localStorage`: rejected, because any compromised dependency or injected script could read a session that may hold permissions such as refunds or credential management.
- Django session cookies instead of JWT: rejected, because the mobile app and other clients already use the JWT API, and the console and storefront live on other domains than the API.

## Consequences

- This settles the session question left open for the Phase 7 storefront; the storefront only changes who signs in (customers instead of staff).
- The mobile app keeps using JWT directly, with its tokens in the platform's secure storage.
- Enabling the blacklist adds the `token_blacklist` app and its migration to the backend.
