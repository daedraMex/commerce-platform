---
status: accepted
---

# Product labels encode one fixed label link on a group subdomain, and the platform redirects it

Each piece gets one product label, and its QR code serves both staff and customers, so no second shelf label is printed. The QR code encodes a label link, `https://q.berlekgroup.com/<store>/<SKU>`, where `<store>` is the store's slug and `<SKU>` is the variant's SKU. Staff scan it in Quetzal to sell, count and look up prices: Quetzal takes the SKU from the last path segment and also accepts a bare SKU, so labels printed before this decision keep working. A customer who scans it with a phone camera opens the link, and the platform redirects it to that variant's product page, or opens it in the mobile app through universal links and app links (Phase 14).

The label link uses a subdomain of `berlekgroup.com`, the group domain the operator already owns, never a store's own domain. A store can change its brand or its domain, and a product line can move to another brand, without breaking a single printed label. The store slug is in the path because a SKU is unique only within its store. The link never contains the product page URL, so the storefront can change its page URLs later by changing only the redirect.

## Considered Options

- A product label with the bare SKU plus a separate shelf label with the product URL: rejected. It prints two labels for every product, and the shelf label breaks if the page URL ever changes.
- Each store's own domain, such as `https://<store-domain>/p/<SKU>`: rejected. Every store would need its final domain before the first label is printed, and renaming a brand or moving a line to another brand would break its printed labels.
- A new short domain bought for the group: rejected for now. It gives a slightly smaller QR code, but it costs money and adds a domain to keep; the group subdomain is already owned. If the 63x22 mm keychain tag turns out hard to scan, this is the fallback, and only new labels would use it.

## Consequences

- The label link format never changes once the first label is printed; the label script and Phase 5c print only this format.
- Until Phase 6a, `q.berlekgroup.com` redirects from the `berlekgroup.com` hosting to a temporary page, such as the TikTok Shop or WhatsApp. From Phase 6a it points to the platform, which owns the redirect; an unknown store or SKU gets a plain not-found page.
- Before printing in bulk, a test label on the 63x22 mm keychain tag confirms the QR code scans with both the USB scanner and a phone camera.
- The label link is not the public product URL: Phase 7 chooses the product page URLs freely.
