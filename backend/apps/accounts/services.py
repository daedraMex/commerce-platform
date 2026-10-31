from apps.accounts.models import Role, StoreMembership


def grant_membership(*, user, store, role_name):
    """Make ``user`` active staff of ``store`` with the role named ``role_name``.

    A user holds one membership per store, so an existing one, active or not, is
    reactivated with the new role instead of adding a row.
    """
    try:
        role = Role.objects.get(name=role_name)
    except Role.DoesNotExist as error:
        raise ValueError(f"Unknown role {role_name!r}.") from error
    membership, _ = StoreMembership.objects.update_or_create(
        user=user, store=store, defaults={"role": role, "is_active": True}
    )
    return membership


def get_active_membership(*, user, store_id):
    """Return the active membership of ``user`` in the store, or None.

    An inactive membership grants nothing, so it is never returned.
    """
    if not user.is_authenticated:
        return None
    return (
        StoreMembership.objects.select_related("store", "role")
        .prefetch_related("role__permissions")
        .filter(user=user, store_id=store_id, is_active=True)
        .first()
    )
