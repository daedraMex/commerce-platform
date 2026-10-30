---
status: accepted
---

# Roles start restrictive, and content_editor posts are approved by owner or store_admin

The five seeded roles get their permissions in the same data migration that creates them. Refunds are owner-only, and approving social posts is kept away from the role that writes them, so every post proposed by content_editor is approved by an owner or store_admin. We start restrictive because widening a role later is a new data migration, while narrowing it after people rely on it is a disruption.

| Role | `orders.place_manual` | `orders.refund` | `inventory.adjust` | `catalog.manage` | `social.approve_post` |
| --- | --- | --- | --- | --- | --- |
| `owner` | yes | yes | yes | yes | yes |
| `store_admin` | yes | | yes | yes | yes |
| `content_editor` | | | | yes | |
| `warehouse` | | | yes | | |
| `support` | yes | | | | |

## Consequences

- Changing an assignment is a new data migration; the seeding migration is never edited.
- `content_editor` proposes social posts but never approves them; Phase 9 adds a propose permission (such as `social.propose_post`) for it.
- The future `memberships.manage` and `credentials.manage` permissions are owner-only by default.
