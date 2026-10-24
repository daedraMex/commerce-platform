# No business or organization entity above Store, and one platform-wide list of roles

There is no Business, Organization or Merchant entity above Store yet. Owner is a role a User holds through a store membership in each store, and the platform operator is the Django superuser, outside any store. Roles come from one platform-wide list and are assigned per store; per-store custom roles are not supported. Adding a level above Store is part of the SaaS isolation decision that ADR-0001 deliberately defers, so it is not anticipated now.

## Consequences

- An owner of both stores holds two store memberships, one per store.
- When the SaaS model is chosen, a tenant level may be introduced above Store and roles may become tenant-specific; nothing built now may assume either.
