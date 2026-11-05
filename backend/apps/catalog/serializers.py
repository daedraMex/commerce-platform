from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


def _option_values(variant):
    category = variant.product.category
    selected = variant.option_values or {}
    values = []
    for option in category.option_schema:
        code = option["code"]
        value_code = selected.get(code)
        definition = next(
            (value for value in option["values"] if value["code"] == value_code),
            None,
        )
        values.append(
            {
                "code": code,
                "label": option["label"],
                "value": {
                    "code": value_code,
                    "label": definition["label"] if definition else None,
                    "width_cm": definition.get("width_cm") if definition else None,
                    "height_cm": definition.get("height_cm") if definition else None,
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


class ProductSummarySerializer(serializers.Serializer):
    name = serializers.CharField()
    slug = serializers.CharField()


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
