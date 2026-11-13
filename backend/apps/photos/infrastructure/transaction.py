"""Django implementation of the photo application's UnitOfWork port."""

from django.db import transaction


class DjangoPhotoUnitOfWork:
    """Run one use case's catalog change and submission save in one transaction."""

    def __call__(self):
        return transaction.atomic()
