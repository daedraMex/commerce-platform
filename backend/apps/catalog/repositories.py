"""Django implementations of the catalog service's ports (ADR-0028)."""

from apps.catalog.media import PreparedMedia, save_prepared_media
from apps.catalog.models import Media, Product, ProductMedia, ProductVariant
from apps.catalog.services import (
    CategoryReference,
    MediaRecord,
    NewMedia,
    NewProductImage,
    ProductImageRecord,
    ProductImageRole,
    ProductRecord,
    VariantRecord,
)


def _media_record(row):
    return MediaRecord(
        id=row.pk,
        store_id=row.store_id,
        storage_key=row.storage_key,
        content_hash=row.content_hash,
        mime_type=row.mime_type,
        alt_text=row.alt_text,
        width=row.width,
        height=row.height,
        metadata=row.metadata,
    )


def _product_record(row):
    return ProductRecord(
        id=row.pk,
        store_id=row.store_id,
        name=row.name,
        slug=row.slug,
        category=CategoryReference(
            id=row.category_id,
            shape=row.category.shape,
            option_schema=tuple(row.category.option_schema or ()),
        ),
    )


def _variant_record(row):
    return VariantRecord(
        id=row.pk,
        store_id=row.store_id,
        product_id=row.product_id,
        sku=row.sku,
        option_values=row.option_values,
    )


def _image_record(row):
    return ProductImageRecord(
        id=row.pk,
        store_id=row.product.store_id,
        product_id=row.product_id,
        media_id=row.media_id,
        variant_id=row.variant_id,
        role=ProductImageRole(row.role),
        position=row.position,
        is_active=row.is_active,
    )


class DjangoCatalogRepository:
    """Read and write catalog rows, filtering every query by store."""

    def media_by_content_hash(self, store_id: int, content_hash: str) -> MediaRecord | None:
        row = Media.objects.filter(store_id=store_id, content_hash=content_hash).first()
        return _media_record(row) if row is not None else None

    def media_by_id(self, store_id: int, media_id: int) -> MediaRecord | None:
        row = Media.objects.filter(pk=media_id, store_id=store_id).first()
        return _media_record(row) if row is not None else None

    def add_media(self, store_id: int, media: NewMedia) -> MediaRecord:
        row = Media.objects.create(
            store_id=store_id,
            storage_key=media.storage_key,
            content_hash=media.content_hash,
            mime_type=media.mime_type,
            alt_text=media.alt_text,
            width=media.width,
            height=media.height,
            metadata=media.metadata,
        )
        return _media_record(row)

    def get_product(self, store_id: int, product_id: int) -> ProductRecord | None:
        row = (
            Product.objects.filter(pk=product_id, store_id=store_id)
            .select_related("category")
            .first()
        )
        return _product_record(row) if row is not None else None

    def get_variant(self, store_id: int, variant_id: int) -> VariantRecord | None:
        row = ProductVariant.objects.filter(pk=variant_id, store_id=store_id).first()
        return _variant_record(row) if row is not None else None

    def get_product_image(self, image_id: int) -> ProductImageRecord | None:
        row = ProductMedia.objects.filter(pk=image_id).select_related("product").first()
        return _image_record(row) if row is not None else None

    def find_product_image(self, product_id: int, media_id: int) -> ProductImageRecord | None:
        row = ProductMedia.objects.filter(product_id=product_id, media_id=media_id).first()
        return _image_record(row) if row is not None else None

    def active_main_image(self, product_id: int) -> ProductImageRecord | None:
        row = ProductMedia.objects.filter(
            product_id=product_id,
            role=ProductMedia.Role.MAIN,
            is_active=True,
        ).first()
        return _image_record(row) if row is not None else None

    def add_product_image(self, image: NewProductImage) -> ProductImageRecord:
        row = ProductMedia.objects.create(
            product_id=image.product_id,
            media_id=image.media_id,
            variant_id=image.variant_id,
            role=image.role.value,
            position=image.position,
        )
        return _image_record(row)

    def save_product_image(self, image: ProductImageRecord) -> ProductImageRecord:
        row = ProductMedia.objects.select_related("product").get(pk=image.id)
        row.variant_id = image.variant_id
        row.role = image.role.value
        row.position = image.position
        row.is_active = image.is_active
        row.save(update_fields=["variant", "role", "position", "is_active"])
        return _image_record(row)


class DjangoMediaFiles:
    """Write media bytes and their renditions with the catalog media pipeline."""

    def store(self, media: NewMedia) -> None:
        save_prepared_media(
            PreparedMedia(
                content=media.content,
                content_hash=media.content_hash,
                storage_key=media.storage_key,
                mime_type=media.mime_type,
                width=media.width,
                height=media.height,
                metadata=media.metadata,
            )
        )
