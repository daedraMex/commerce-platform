from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower

from apps.accounts.managers import UserManager


class User(AbstractUser):
    """A person's single login account, identified by an email unique platform-wide."""

    username = None
    email = models.EmailField("email address", unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="accounts_user_email_ci_unique",
                violation_error_message="A user with this email already exists.",
            ),
        ]

    def save(self, *args, **kwargs):
        self.email = UserManager.normalize_email(self.email)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email


class Permission(models.Model):
    """An action a role may allow in a store, named by a code such as ``orders.refund``.

    Not Django's ``auth.Permission``, which only gates the admin.
    """

    code = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ("code",)

    def __str__(self):
        return self.code


class Role(models.Model):
    """A named set of permissions from one platform-wide list (ADR-0012)."""

    name = models.CharField(max_length=50, unique=True)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class StoreMembership(models.Model):
    """Makes a User staff of one store, with exactly one role there."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="store_memberships")
    store = models.ForeignKey("stores.Store", on_delete=models.PROTECT, related_name="memberships")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="memberships")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("store", "user")
        constraints = [
            # Unconditional, so an inactive membership still holds the slot and is reactivated.
            models.UniqueConstraint(
                fields=("user", "store"),
                name="accounts_storemembership_user_store_unique",
                violation_error_message="This user already has a membership in this store.",
            ),
        ]

    def __str__(self):
        return f"{self.user} in {self.store} as {self.role}"
