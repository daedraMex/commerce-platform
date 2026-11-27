# Catalog contracts

The contracts of the catalog module, as merged code implements them (ADR-0031). Each
heading is a contract id for a ticket's **Contracts** section. A pull request that changes
one updates this file and every consumer in the same pull request.

## catalog.definition-file

**Owner:** #252 (Phase 6a `load_catalog_schema`)

A store's **catalog definition** is one versioned JSON file per store (GLOSSARY.md,
ADR-0024). It lists the store's suppliers and categories before its catalog rows are
imported, and it may evolve while the catalog is being finished.

```json
{
  "version": 1,
  "store": "home",
  "suppliers": ["Beka", "Por definir"],
  "categories": [
    {
      "slug": "frazada",
      "name": "Frazada",
      "sku_code": "FRZ",
      "shape": "rectangle",
      "option_schema": [
        {
          "code": "size",
          "label": "Size",
          "values": [
            {"code": "IND", "label": "Individual", "width_cm": 150, "height_cm": 200},
            {"code": "MAT", "label": "Matrimonial", "width_cm": 195, "height_cm": 220}
          ]
        }
      ],
      "attribute_schema": [
        {
          "code": "material",
          "label": "Material",
          "type": "text",
          "choices": [],
          "required": true
        }
      ]
    }
  ]
}
```

**Top level**

| Key | Required | Meaning |
|---|---|---|
| `version` | no, defaults to `1` | Format version. Only `1` is accepted; another number is rejected as unsupported. |
| `store` | no | Store slug the file belongs to. When present it must equal `--store`, so a file cannot be loaded into another store by mistake. |
| `suppliers` | yes | List of suppliers. |
| `categories` | yes | List of categories. |

Unknown top-level keys are ignored, so an evolving file can carry comments-like metadata
without breaking the command. The lists may be empty.

**Suppliers**

- Each entry is either a supplier name (`"Beka"`) or an object with a `name`
  (`{"name": "Beka"}`).
- Names are trimmed and matched exactly, as `import_catalog` matches them; two entries with
  the same name are rejected.
- The command always makes sure the glossary's placeholder supplier **"Por definir"**
  exists, even when the file omits it.
- An existing supplier is never deleted or deactivated by this command; the file has no
  active flag.

**Categories**

| Key | Required | Meaning |
|---|---|---|
| `slug` | yes | Identity of the category in its store; normalized the same way as `Category.slug`. Two entries that normalize to the same slug are rejected. |
| `name` | yes | Display name. |
| `sku_code` | yes | Uppercased SKU prefix. A used code cannot change (see below). |
| `shape` | no, defaults to `rectangle` | `rectangle` or `contour` (`Category.Shape`). |
| `option_schema` | no, defaults to `[]` | ADR-0024 option schema, validated before anything is written. |
| `attribute_schema` | no, defaults to `[]` | ADR-0024 attribute schema, validated before anything is written. |

Unknown category keys are ignored. As a convenience, `categories` may also be a JSON
object keyed by slug; the canonical form is the list shown above.

## catalog.load-schema-command

**Owner:** #252

```text
load_catalog_schema --store <slug> --file <catalog-definition.json> [--dry-run]
```

- Requires an existing active store; an unknown or inactive slug fails with `CommandError`.
- Reads a `catalog.definition-file`, validates its JSON shape and every category schema,
  then applies the whole file in one transaction.
- **Identity and upsert:** suppliers by exact `name`, categories by normalized `slug`.
  Existing rows get the file's name, `sku_code`, shape and schemas. Rows missing from the
  file are left untouched, never deleted or deactivated, so the command converges on
  re-run and is safe while the file evolves.
- **Never change a used `sku_code`:** the model rejects a change when any variant was
  generated from it, and the command turns that into a clear `CommandError`. Before the
  first variant it may change, which is what lets a schema be fixed while the catalog is
  being finished.
- **Validate first, write once:** an invalid file, schema, duplicate slug/supplier, or a
  change that would invalidate an existing product or variant rejects the whole load with
  `CommandError`; nothing is written, including the placeholder supplier.
- **Diff report:** prints category/supplier create, update and unchanged counts plus, for
  each category, its created values or the exact `field: old -> new` changes.
- **`--dry-run`:** prints the same diff and writes nothing, including no placeholder
  supplier, no category and no supplier. It still runs every validation, so a used
  `sku_code` change is refused in a dry run too.
