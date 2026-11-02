from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from apps.shared.domain.store import STORE_SLUG_MAX_LENGTH, is_valid_store_slug

FEATURE_FLAG_CODE_MAX_LENGTH = STORE_SLUG_MAX_LENGTH


def validate_store_slug(value):
    if not is_valid_store_slug(value):
        raise ValidationError(
            "Use lowercase letters and digits separated by single hyphens.",
            code="invalid_store_slug",
        )


def validate_feature_flag_code(value):
    # Flag codes follow the store slug rule, but a bad one must not read as a bad store slug.
    if not is_valid_store_slug(value):
        raise ValidationError(
            "Use lowercase letters and digits separated by single hyphens.",
            code="invalid_feature_flag_code",
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


class StoreFeatureFlag(models.Model):
    """Whether a feature is on for one store; edited only by the platform operator (ADR-0013).

    Codes follow the store slug rule and are declared as constants next to their feature.
    """

    store = models.ForeignKey(Store, on_delete=models.PROTECT, related_name="feature_flags")
    code = models.CharField(
        max_length=FEATURE_FLAG_CODE_MAX_LENGTH, validators=[validate_feature_flag_code]
    )
    enabled = models.BooleanField(default=False)

    class Meta:
        ordering = ("store", "code")
        constraints = [
            models.UniqueConstraint(
                fields=("store", "code"), name="stores_storefeatureflag_store_code_unique"
            ),
        ]

    def __str__(self):
        return f"{self.store} / {self.code}"
