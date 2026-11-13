---
status: accepted
---

# Product photos wait for staff approval and form an ordered carousel whose first image is the cover

This decision replaces one rule of ADR-0028, which said that an individual photo becomes its product's main image as soon as it is processed. Processing now only makes a photo submission `ready`. Nothing reaches the storefront until a staff member approves it.

Each product shows a carousel: its active product images, ordered by position. The image at position 1 is the cover, the one shown in product listings, search and social posts. Catalog keeps the `main` role on the cover's link so the existing one-main constraint and readers still work; every other active link has the `gallery` role. Approving a ready photo links its Media as an active image at the end of the carousel. If the product has no active images, that image becomes the cover. Staff change the order, and therefore the cover, by dragging in Quetzal; catalog renumbers positions and moves the `main` role to the new first image in one transaction. Removing a photo from the carousel deactivates its link without deleting the Media or the link. Approving it again reactivates the link at the end of the carousel. A group photo follows the same rule for each product it is approved for.

In Quetzal, a ready photo that has not been approved, or a removed one, is shown with a grey, inactive border, and the images in the carousel are shown with the store's accent border.

## Considered Options

- Processing links the result as the main image automatically (ADR-0028 as written): rejected. A crooked or dark shot would replace the published image before anyone sees it, and the staff approve, redo and discard actions would have nothing left to decide.
- A cover chosen with its own button, independent of the order: rejected. Two controls for one idea; the first image in the order is what customers see first anyway.
- Ordering by approval date only: rejected. Staff need to pick which photo leads without re-uploading.
- Approved photos cannot be removed, only reordered: rejected. Products change and a shot can go stale; removal is a deactivation, so nothing is lost.

## Consequences

- The photos processing task (B12) never links Media to products; it only records `ready` or `failed`.
- The photos apply action (B11) appends to the carousel through the catalog service instead of replacing the main image, and a remove action is added. Both stay behind `catalog.manage` through the Authorizer.
- Catalog's product-image service gains append, deactivate and reorder operations that keep exactly one active `main` link, the cover, at position 1.
- `ROADMAP.md` and `phase-prompts.md` describe the Phase 4b exit criterion with this approval step.
