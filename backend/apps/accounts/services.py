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
        _active_memberships(user_id=user.id, store_id=store_id)
        .select_related("store", "role")
        .prefetch_related("role__permissions")
        .first()
    )


def has_store_permission(*, user_id, store_id, permission):
    """Return whether the user's active membership in the store has a role holding ``permission``.

    An inactive user or an inactive store grants nothing. There is no bypass for superusers
    or ``is_staff`` (ADR-0019).
    """
    return (
        _active_memberships(user_id=user_id, store_id=store_id)
        .filter(role__permissions__code=permission)
        .exists()
    )


def _active_memberships(*, user_id, store_id):
    # The one definition of an active membership, shared by IsStoreStaff and the Authorizer.
    # The user and the store must be active too: the Authorizer also runs from use cases,
    # Celery tasks and agents, where no authentication or store resolver has run (ADR-0019).
    return StoreMembership.objects.filter(
        user_id=user_id,
        store_id=store_id,
        is_active=True,
        user__is_active=True,
        store__is_active=True,
    )
