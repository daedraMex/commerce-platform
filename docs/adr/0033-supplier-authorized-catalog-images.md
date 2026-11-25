---
status: accepted
---

# Catalog images may come from a supplier that authorized them in writing, never with its watermark

A catalog image is either our own photo or an image its supplier authorized in writing for our store and social media. On 2026-11-07 Beka authorized us, by WhatsApp, to use the design images from its catalog PDFs; the store operator keeps that message outside the repository. In those PDFs the BK watermark is a separate layer drawn over each image, so the embedded images are extracted clean: no watermark is removed or edited out, and an image that still shows a watermark is never uploaded. We take this because photographing more than 1,000 designs before the storefront opens is not possible, and the supplier's images are the only complete set we have.

## Considered Options

- Our own photos only (the previous rule in `AGENTS.md`): rejected for now. It blocks the launch on photographing every design; our photos stay the preferred source.
- Removing the watermark from the rendered catalog pages: rejected. It is not needed for Beka, whose images come clean from the PDF, and any other supplier's images need that supplier's own written authorization first.

## Consequences

- Each supplier whose images we use is recorded here or in a later ADR, with what it authorized, when, and where the proof is kept. Beka is the only one today.
- The authorization covers the supplier's images only. It grants no rights to third-party characters, brands or likenesses printed on the products, which stays an open question per product line.
- Our own photos are added through Quetzal (Phase 4b, ADR-0030); dragging one to the first position makes it the cover in place of the supplier image, and removing the supplier image only deactivates its link.
- Beka's images are about 550 px on the short side, and renditions never upscale. The storefront (Phase 7) offers zoom only on images whose original is at least 1,200 px wide, so supplier images show at their own size without zoom while our own photos can be zoomed.
