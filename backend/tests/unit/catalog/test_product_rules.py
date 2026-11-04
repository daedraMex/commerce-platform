from decimal import Decimal

import pytest

from apps.catalog.rules import (
    CatalogRuleError,
    build_sku,
    default_product_name,
    normalize_sku,
    validate_option_values,
    validate_prices,
    validate_product_attributes,
)

ATTRIBUTE_SCHEMA = [
    {
        "code": "material",
        "label": "Material",
        "type": "text",
        "choices": [],
        "required": True,
    },
    {
        "code": "finish",
        "label": "Finish",
        "type": "choice",
        "choices": ["Matte", "Gloss"],
        "required": False,
    },
    {
        "code": "grams",
        "label": "Grams",
        "type": "number",
        "choices": [],
        "required": False,
    },
    {
        "code": "reversible",
        "label": "Reversible",
        "type": "boolean",
        "choices": [],
        "required": False,
    },
]

OPTION_SCHEMA = [
    {
        "code": "size",
        "label": "Size",
        "values": [
            {"code": "IND", "label": "Individual", "width_cm": 110, "height_cm": 160},
            {"code": "MAX", "label": "Maxi", "width_cm": 175, "height_cm": 160},
            {"code": "MAT", "label": "Matrimonial", "width_cm": 210, "height_cm": 160},
        ],
    }
]


def test_valid_attributes_pass():
    validate_product_attributes(
        {"material": "Flannel premier", "finish": "Matte", "grams": 900, "reversible": True},
        ATTRIBUTE_SCHEMA,
    )


def test_missing_optional_attributes_pass():
    validate_product_attributes({"material": "Flannel premier"}, ATTRIBUTE_SCHEMA)


def test_an_empty_attribute_set_passes_without_a_schema():
    validate_product_attributes({}, [])


@pytest.mark.parametrize(
    ("attributes", "needle"),
    [
        ({}, "material"),
        ({"material": ""}, "material"),
        ({"material": 12}, "material"),
        ({"material": "Flannel", "grams": "heavy"}, "grams"),
        ({"material": "Flannel", "grams": True}, "grams"),
        ({"material": "Flannel", "reversible": "yes"}, "reversible"),
        ({"material": "Flannel", "finish": "Satin"}, "finish"),
        ({"material": "Flannel", "weight": 2}, "weight"),
    ],
)
def test_invalid_attributes_are_rejected_naming_the_attribute(attributes, needle):
    with pytest.raises(CatalogRuleError) as error:
        validate_product_attributes(attributes, ATTRIBUTE_SCHEMA)

    assert needle in str(error.value)


def test_valid_option_values_pass():
    validate_option_values({"size": "MAT"}, OPTION_SCHEMA)


def test_a_category_without_options_accepts_no_option_values():
    validate_option_values({}, [])


@pytest.mark.parametrize(
    ("option_values", "needle"),
    [
        ({}, "size"),
        ({"color": "RED"}, "color"),
        ({"size": "GIGANTIC"}, "GIGANTIC"),
        ({"size": ""}, "size"),
    ],
)
def test_invalid_option_values_are_rejected_naming_the_problem(option_values, needle):
    with pytest.raises(CatalogRuleError) as error:
        validate_option_values(option_values, OPTION_SCHEMA)

    assert needle in str(error.value)


def test_every_option_needs_exactly_one_value():
    schema = [
        *OPTION_SCHEMA,
        {
            "code": "color",
            "label": "Color",
            "values": [{"code": "RED", "label": "Red"}],
        },
    ]

    with pytest.raises(CatalogRuleError) as error:
        validate_option_values({"size": "MAT"}, schema)

    assert "color" in str(error.value)


def test_the_sku_uses_the_category_code_design_number_and_option_codes():
    assert build_sku("FRZ", 12, OPTION_SCHEMA, {"size": "MAT"}) == "FRZ-00012-MAT"


def test_the_sku_keeps_a_multi_part_option_code():
    schema = [
        {
            "code": "size",
            "label": "Size",
            "values": [{"code": "DON-80", "label": "Donut", "width_cm": 80, "height_cm": 80}],
        }
    ]

    assert build_sku("ALM", 12, schema, {"size": "DON-80"}) == "ALM-00012-DON-80"


def test_the_sku_has_no_suffix_for_a_category_without_options():
    assert build_sku("FRZ", 12, [], {}) == "FRZ-00012"


def test_sku_parts_are_uppercased():
    assert build_sku("frz", 12, OPTION_SCHEMA, {"size": "mat"}) == "FRZ-00012-MAT"


def test_multi_option_suffixes_follow_the_schema_order():
    schema = [
        *OPTION_SCHEMA,
        {
            "code": "color",
            "label": "Color",
            "values": [{"code": "RED", "label": "Red"}],
        },
    ]

    assert build_sku("FRZ", 12, schema, {"color": "RED", "size": "MAT"}) == "FRZ-00012-MAT-RED"


def test_a_sku_is_normalized_to_uppercase():
    assert normalize_sku("  frz-00012-mat  ") == "FRZ-00012-MAT"


def test_valid_prices_pass():
    validate_prices(Decimal("199.00"), None, Decimal("80.00"))
    validate_prices(Decimal("199.00"), Decimal("249.00"), Decimal("0.00"))


@pytest.mark.parametrize(
    ("price", "compare_at_price", "cost", "needle"),
    [
        (None, None, Decimal("80.00"), "price"),
        (Decimal("0.00"), None, Decimal("80.00"), "greater than zero"),
        (Decimal("-1.00"), None, Decimal("80.00"), "greater than zero"),
        (Decimal("199.00"), Decimal("199.00"), Decimal("80.00"), "compare-at"),
        (Decimal("199.00"), Decimal("150.00"), Decimal("80.00"), "compare-at"),
        (Decimal("199.00"), None, None, "cost"),
        (Decimal("199.00"), None, Decimal("-0.01"), "negative"),
    ],
)
def test_invalid_prices_are_rejected(price, compare_at_price, cost, needle):
    with pytest.raises(CatalogRuleError) as error:
        validate_prices(price, compare_at_price, cost)

    assert needle in str(error.value)


def test_the_default_product_name_joins_the_category_and_design():
    assert default_product_name("Frazada", "Jack Todos") == "Frazada Jack Todos"


def test_the_default_product_name_works_without_a_design():
    assert default_product_name("Frazada", None) == "Frazada"
