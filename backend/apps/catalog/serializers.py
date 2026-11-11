from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


def _option_values(variant):
    category = variant.product.category
    selected = variant.option_values or {}
    values = []
    for option in category.option_schema:
        code = option["code"]
        value_code = selected.get(code)
        definition = (
            next(
                (value for value in option["values"] if value["code"] == value_code),
                None,
            )
            or {}
        )
        values.append(
            {
                "code": code,
                "label": option["label"],
                "value": {
                    "code": value_code,
                    "label": definition.get("label"),
                    "width_cm": definition.get("width_cm"),
                    "height_cm": definition.get("height_cm"),
                },
            }
        )
    return values


def _attributes(product):
    schema = product.category.attribute_schema
    values = product.attributes or {}
    return [
        {
            "code": entry["code"],
            "label": entry["label"],
            "type": entry["type"],
            "value": values[entry["code"]],
        }
        for entry in schema
        if entry["code"] in values
    ]


class OptionValueSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    width_cm = serializers.FloatField(allow_null=True, required=False)
    height_cm = serializers.FloatField(allow_null=True, required=False)


class OptionSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    values = OptionValueSerializer(many=True)


class CategorySerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()
    sku_code = serializers.CharField()
    shape = serializers.CharField()
    options = OptionSerializer(source="option_schema", many=True)


class CategorySummarySerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()


class CollectionSummarySerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()
    description = serializers.CharField()


class VariantOptionSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    value = OptionValueSerializer()


class AttributeSerializer(serializers.Serializer):
    code = serializers.CharField()
    label = serializers.CharField()
    type = serializers.CharField()
    value = serializers.JSONField()


class VariantSerializer(serializers.Serializer):
    sku = serializers.CharField()
    options = serializers.SerializerMethodField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)
    compare_at_price = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        allow_null=True,
    )

    @extend_schema_field(VariantOptionSerializer(many=True))
    def get_options(self, variant):
        return _option_values(variant)


class ProductImageSerializer(serializers.Serializer):
    url = serializers.CharField(source="media.public_url")
    thumbnail_url = serializers.CharField(source="media.thumbnail_url")
    medium_url = serializers.CharField(source="media.medium_url")
    role = serializers.CharField()
    position = serializers.IntegerField()
    alt_text = serializers.CharField(source="media.alt_text")
    width = serializers.IntegerField(source="media.width")
    height = serializers.IntegerField(source="media.height")
    variant = serializers.SerializerMethodField()

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_variant(self, image):
        return image.variant.sku if image.variant_id is not None else None


def _main_image(product):
    return next(
        (
            image
            for image in product.product_media.all()
            if image.role == "main" and image.is_active
        ),
        None,
    )


class ProductSummarySerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()
    main_image = serializers.SerializerMethodField()

    @extend_schema_field(ProductImageSerializer)
    def get_main_image(self, product):
        image = _main_image(product)
        return ProductImageSerializer(image).data if image is not None else None


class StaffProductSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    category = CategorySummarySerializer()
    needs_main_image = serializers.SerializerMethodField()
    main_image = serializers.SerializerMethodField()

    @extend_schema_field(serializers.BooleanField())
    def get_needs_main_image(self, product):
        return _main_image(product) is None

    @extend_schema_field(ProductImageSerializer)
    def get_main_image(self, product):
        image = _main_image(product)
        return ProductImageSerializer(image).data if image is not None else None


class VariantLookupSerializer(VariantSerializer):
    product = ProductSummarySerializer()


class ProductSerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()
    category = CategorySummarySerializer()
    attributes = serializers.SerializerMethodField()
    variants = serializers.SerializerMethodField()

    @extend_schema_field(AttributeSerializer(many=True))
    def get_attributes(self, product):
        return _attributes(product)

    @extend_schema_field(VariantSerializer(many=True))
    def get_variants(self, product):
        variants = sorted(
            (variant for variant in product.variants.all() if variant.is_active),
            key=lambda variant: variant.sku,
        )
        return VariantSerializer(variants, many=True).data


class ProductDetailSerializer(ProductSerializer):
    description = serializers.CharField()
    collections = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()

    @extend_schema_field(CollectionSummarySerializer(many=True))
    def get_collections(self, product):
        memberships = product.collection_memberships.all()
        return CollectionSummarySerializer(
            [membership.collection for membership in memberships], many=True
        ).data

    @extend_schema_field(ProductImageSerializer(many=True))
    def get_images(self, product):
        return ProductImageSerializer(product.product_media.all(), many=True).data
