from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from apps.shared.domain.store import STORE_SLUG_MAX_LENGTH, is_valid_store_slug


def validate_store_slug(value):
    if not is_valid_store_slug(value):
        raise ValidationError(
            "Use lowercase letters and digits separated by single hyphens.",
            code="invalid_store_slug",
        )


def normalize_domain(value):
    """Lowercase a domain; no domain is NULL, never "", so domainless stores never collide."""
    return value.lower() if value else None


class Store(models.Model):
    """A store the platform serves; stores are data, deactivated and never deleted."""

    slug = models.CharField(
        max_length=STORE_SLUG_MAX_LENGTH, unique=True, validators=[validate_store_slug]
    )
    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=253, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("slug",)
        constraints = [
            # Guards writes that skip save(), such as QuerySet.update(), as ADR-0015 does for email.
            models.CheckConstraint(
                condition=models.Q(domain__isnull=True)
                | (models.Q(domain=Lower("domain")) & ~models.Q(domain="")),
                name="stores_store_domain_lowercase_or_null",
            ),
        ]

    def __str__(self):
        return self.slug

    def save(self, *args, **kwargs):
        self.domain = normalize_domain(self.domain)
        super().save(*args, **kwargs)

    def clean(self):
        # Runs before the admin's unique checks, so they compare the stored form.
        self.domain = normalize_domain(self.domain)
