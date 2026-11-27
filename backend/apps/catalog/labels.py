import logging
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_safe

from apps.catalog.models import ProductVariant
from apps.stores.services import get_store_by_slug

logger = logging.getLogger(__name__)

LABEL_NOT_FOUND_TEMPLATE = "catalog/label_not_found.html"
WHATSAPP_TARGET = "https://wa.me/{number}?text={text}"


def _digits(value):
    return "".join(character for character in (value or "") if character.isdigit())


def _whatsapp_url(number, text):
    return WHATSAPP_TARGET.format(number=quote(number, safe=""), text=quote(text, safe=""))


def _whatsapp_number(store):
    return store.whatsapp_number or _digits(settings.LABEL_WHATSAPP_NUMBER)


def _visible_variant(store, sku):
    """The store's variant the label may target, or None without a label-wide leak.

    Matches the public variant lookup: the variant, its product and its category must be
    active, and the store filter keeps another store's SKU from answering this link.
    """
    return (
        ProductVariant.objects.filter(
            store=store,
            sku__iexact=sku,
            is_active=True,
            product__is_active=True,
            product__category__is_active=True,
        )
        .select_related("product")
        .first()
    )


@require_safe
def label_redirect(request, store_slug, sku):
    """Redirect a printed label link to the store's contact target (ADR-0035)."""
    store = get_store_by_slug(store_slug)
    known_store = store if store is not None and store.is_active else None

    variant = _visible_variant(known_store, sku) if known_store is not None else None
    number = _whatsapp_number(known_store) if known_store is not None else ""

    if variant is None or not number:
        if variant is not None:
            logger.warning(
                "Label link for store %r has no WhatsApp number configured.",
                known_store.slug,
            )
        return _not_found(request, known_store, number)

    text = f"Hola {known_store.name}, me interesa {variant.sku}"
    return HttpResponseRedirect(_whatsapp_url(number, text))


def _not_found(request, store, number):
    contact_url = ""
    if store is not None and number:
        contact_url = _whatsapp_url(number, f"Hola {store.name}")

    response = render(
        request,
        LABEL_NOT_FOUND_TEMPLATE,
        {"store": store, "contact_url": contact_url},
        status=404,
    )
    response["X-Robots-Tag"] = "noindex"
    return response
