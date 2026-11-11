import re

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from apps.shared.domain.store import STORE_SLUG_MAX_LENGTH, is_valid_store_slug

FEATURE_FLAG_CODE_MAX_LENGTH = STORE_SLUG_MAX_LENGTH

ACCENT_COLOR_DEFAULT = "#4f46e5"
_ACCENT_COLOR_REGEX = re.compile(r"^#[0-9a-fA-F]{6}$")


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


def validate_accent_color(value):
    if not isinstance(value, str) or _ACCENT_COLOR_REGEX.fullmatch(value) is None:
        raise ValidationError(
            "Use a six-digit hex color such as #4f46e5.",
            code="invalid_accent_color",
        )


def normalize_domain(value):
    """Lowercase a domain; no domain is NULL, never "", so domainless stores never collide."""
    return value.lower() if value else None


def normalize_accent_color(value):
    """Lowercase a hex color; the database constraint stores only lowercase hex."""
    return value.lower() if value else value


class Store(models.Model):
    """A store the platform serves; stores are data, deactivated and never deleted."""

    slug = models.CharField(
        max_length=STORE_SLUG_MAX_LENGTH, unique=True, validators=[validate_store_slug]
    )
    name = models.CharField(max_length=200)
    domain = models.CharField(max_length=253, unique=True, null=True, blank=True)
    accent_color = models.CharField(
        max_length=7,
        blank=True,
        default=ACCENT_COLOR_DEFAULT,
        validators=[validate_accent_color],
    )
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
            models.CheckConstraint(
                condition=models.Q(accent_color__regex=r"^#[0-9a-f]{6}$"),
                name="stores_store_accent_color_hex",
            ),
        ]

    def __str__(self):
        return self.slug

    def save(self, *args, **kwargs):
        self.domain = normalize_domain(self.domain)
        self.accent_color = normalize_accent_color(self.accent_color)
        super().save(*args, **kwargs)

    def clean(self):
        # Runs before the admin's unique checks and the constraint check, so both compare
        # the stored form.
        self.domain = normalize_domain(self.domain)
        self.accent_color = normalize_accent_color(self.accent_color)
        # The field's validator skips "", which blank=True lets through; validate it here.
        if self.accent_color == "":
            try:
                validate_accent_color(self.accent_color)
            except ValidationError as error:
                raise ValidationError({"accent_color": error}) from error


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
