from apps.stores.models import Store


def lock_store(store_id: int) -> None:
    """Lock a store row until the current transaction ends.

    Other modules use this to serialize per-store sequences without touching the
    stores models themselves.
    """
    Store.objects.select_for_update().only("pk").get(pk=store_id)
