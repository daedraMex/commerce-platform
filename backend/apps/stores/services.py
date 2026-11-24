from apps.stores.models import Store


def lock_store(store_id: int) -> None:
    """Lock a store row until the current transaction ends.

    Other modules use this to serialize per-store sequences without touching the
    stores models themselves.
    """
    Store.objects.select_for_update().only("pk").get(pk=store_id)


def get_store_by_slug(slug: str) -> Store | None:
    """Return the store with this slug, active or not, or None.

    Management commands in other modules look stores up here instead of reading
    the stores models (AGENTS.md); each caller decides what inactive means.
    """
    return Store.objects.filter(slug=slug).first()
