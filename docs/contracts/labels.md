# Labels contracts

The contracts of the labels feature, as merged code implements them (ADR-0031). Each
heading is a contract id for a ticket's **Contracts** section. A pull request that changes
one updates this file and every consumer in the same pull request.

## labels.label-redirect

**Owner:** #251 (Phase 6a label redirect route)

| | |
|---|---|
| Route | `GET /<store>/<SKU>` at the site root, not under `/api/v1/`; the reserved `media/`, `static/`, `admin/` and `api/` prefixes are not label stores |
| Store | The path segment is the store slug; only an active store answers |
| SKU | The last path segment is the variant SKU, matched ignoring case |
| Visible variant | The variant, its product and its category must be active, and the variant must belong to the store in the path |
| Target template (Phase 6a) | `https://wa.me/<number>?text=<encoded text>` |
| Text | `Hola <store name>, me interesa <SKU>`, with the stored SKU and the whole text URL-encoded |
| Number source | `Store.whatsapp_number` when set; otherwise the shared `LABEL_WHATSAPP_NUMBER` setting |
| Success | `302` to the WhatsApp URL |
| Unknown or inactive store, SKU, product or category | `404` with the friendly HTML page |
| Missing number for an otherwise valid label | `404` with the friendly HTML page |
| Other HTTP methods | `405`; `GET` and `HEAD` are accepted |

### Not-found page

The page is minimal, always carries `X-Robots-Tag: noindex` and a `robots` meta tag with
`noindex`, and leaks no data:

- It shows the phrase "Producto no disponible".
- An unknown or inactive store shows no store name and no contact link.
- A known active store shows its name and a WhatsApp contact link built from the same
  resolved number, with the text `Hola <store name>`.
- It never shows the requested SKU, another store's data, or whether a SKU exists
  somewhere else.

### Placeholders

- `<store>` is the store slug, which never changes once the store is created.
- `<SKU>` is the variant SKU, which never changes once created (ADR-0035).
- `<number>` is digits only, country code included, as `wa.me` expects them. A store
  number is stored normalized to digits; the shared setting is normalized the same way.
- `<store name>` is the current store name from the database.

### Phase 7

Phase 7 changes only the target template to the storefront product page. The route,
`GET /<store>/<SKU>`, and the label link format never change (ADR-0035).
