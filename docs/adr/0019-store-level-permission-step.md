---
status: accepted
---

# Store checks run in a store-level permission step after the store is resolved

This amends ADR-0016. A permission class such as `IsStoreStaff` needs `request.store`, but the store is resolved after DRF's permission checks so that a request without credentials and without an `X-Store` header gets 401, not 400. We keep that order and add a second step: after `StoreScopedMixin` resolves the store, it runs the view's `store_permission_classes` (for example `[IsStoreStaff]`). Every store-scoped request therefore fails in a fixed order: 401 (authentication and global permissions), then 400 (`store_header_missing`, `store_header_invalid`, `store_not_found`), then 403 (store-level permissions).

## Considered Options

- Resolve the store between authentication and permissions: rejected, because an anonymous request without the header would get 400 instead of 401, reversing ADR-0016.
- Let `IsStoreStaff` resolve the store itself: rejected, because it duplicates the resolver and lets the two disagree.

## Consequences

- An inactive store resolves as `store_not_found` through the API.
- The platform operator gets no bypass: `IsStoreStaff` and the Authorizer require an active store membership, also for superusers.
- The Authorizer denies an inactive user or an inactive store, even with an active membership whose role holds the permission. It is called from use cases, Celery tasks and agents, where no authentication or store resolver runs first, so it must not rely on them.
