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
