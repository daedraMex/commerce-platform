# Coding standards

AGENTS.md holds the workflow and architecture rules. This file adds the checks
reviews hold us to.

## Authorization

Any new permission, Authorizer or admin change needs a test for each case:

- **Inactive user**: denied.
- **Inactive store**: denied for store-scoped actions.
- **Inactive membership**: denied, even when the user and store are active.
- **Superuser/operator**: no bypass through the API; the admin is superuser-only
  (ADR-0012).
- **Other store**: denied; prove one store's data never appears in another.

## Admin form tests

Admin tests that POST forms submit only the fields the page renders. Use
`rendered_form_data()` and build inline management data with
`tests/integration/admin_forms.py`. A new inline goes there once, not into each
test.

## Media uploads

Every uploaded image goes through the catalog media pipeline. Tests read the
stored bytes and cover GPS EXIF, EXIF orientation, an embedded ICC profile and a
decompression bomb, using the fixtures in `tests/images.py`.

## Public surface

Do not add public aliases, properties, form fields or compatibility shims
without a caller or a sentence in the spec. Name each concept once.
