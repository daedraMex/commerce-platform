import pytest

from apps.catalog.rules import (
    ActiveProduct,
    CatalogRuleError,
    VariantInUse,
    validate_attribute_schema_change,
    validate_category_sku_code_change,
    validate_option_schema_change,
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
]

OPTION_SCHEMA = [
    {
        "code": "size",
        "label": "Size",
        "values": [
            {"code": "IND", "label": "Individual", "width_cm": 110, "height_cm": 160},
            {"code": "MAX", "label": "Maxi", "width_cm": 175, "height_cm": 160},
        ],
    }
]


def product(name="Frazada Jack Todos", **attributes):
    return ActiveProduct(name=name, attributes=attributes)


def variant(sku="FRZ-00012-IND", **option_values):
    return VariantInUse(sku=sku, option_values=option_values)


def test_adding_an_option_value_is_allowed():
    new_schema = [
        {
            "code": "size",
            "label": "Size",
            "values": [
                *OPTION_SCHEMA[0]["values"],
                {"code": "MAT", "label": "Matrimonial", "width_cm": 210, "height_cm": 160},
            ],
        }
    ]

    validate_option_schema_change(
        OPTION_SCHEMA, new_schema, [variant(size="IND"), variant("FRZ-00012-MAX", size="MAX")]
    )


def test_adding_an_optional_attribute_is_allowed():
    new_schema = [
        *ATTRIBUTE_SCHEMA,
        {
            "code": "care",
            "label": "Care",
            "type": "text",
            "choices": [],
            "required": False,
        },
    ]

    validate_attribute_schema_change(ATTRIBUTE_SCHEMA, new_schema, [product(material="Flannel")])


def test_relabelling_attributes_and_options_is_allowed():
    new_attributes = [
        {**ATTRIBUTE_SCHEMA[0], "label": "Fabric"},
        {**ATTRIBUTE_SCHEMA[1], "label": "Coating"},
    ]
    new_options = [
        {
            "code": "size",
            "label": "Measurements",
            "values": [
                {
                    "code": "IND",
                    "label": "One person",
                    "width_cm": 115,
                    "height_cm": 165,
                },
                {
                    "code": "MAX",
                    "label": "Two people",
                    "width_cm": 180,
                    "height_cm": 165,
                },
            ],
        }
    ]

    validate_attribute_schema_change(
        ATTRIBUTE_SCHEMA,
        new_attributes,
        [product(material="Flannel", finish="Matte")],
    )
    validate_option_schema_change(OPTION_SCHEMA, new_options, [variant(size="IND")])


def test_a_new_required_attribute_is_allowed_without_active_products():
    new_schema = [
        *ATTRIBUTE_SCHEMA,
        {
            "code": "care",
            "label": "Care",
            "type": "text",
            "choices": [],
            "required": True,
        },
    ]

    validate_attribute_schema_change(ATTRIBUTE_SCHEMA, new_schema, [])


def test_a_new_required_attribute_is_rejected_when_an_active_product_exists():
    new_schema = [
        *ATTRIBUTE_SCHEMA,
        {
            "code": "care",
            "label": "Care",
            "type": "text",
            "choices": [],
            "required": True,
        },
    ]

    with pytest.raises(CatalogRuleError) as error:
        validate_attribute_schema_change(
            ATTRIBUTE_SCHEMA, new_schema, [product(material="Flannel")]
        )

    assert "Frazada Jack Todos" in str(error.value)
    assert "care" in str(error.value)


def test_an_existing_attribute_made_required_is_rejected_when_an_active_product_lacks_it():
    new_schema = [
        ATTRIBUTE_SCHEMA[0],
        {**ATTRIBUTE_SCHEMA[1], "required": True},
    ]

    with pytest.raises(CatalogRuleError) as error:
        validate_attribute_schema_change(
            ATTRIBUTE_SCHEMA, new_schema, [product(material="Flannel")]
        )

    assert "Frazada Jack Todos" in str(error.value)
    assert "finish" in str(error.value)


def test_removing_a_choice_in_use_is_rejected():
    new_schema = [
        ATTRIBUTE_SCHEMA[0],
        {**ATTRIBUTE_SCHEMA[1], "choices": ["Gloss"]},
    ]

    with pytest.raises(CatalogRuleError) as error:
        validate_attribute_schema_change(
            ATTRIBUTE_SCHEMA,
            new_schema,
            [product(material="Flannel", finish="Matte")],
        )

    assert "Frazada Jack Todos" in str(error.value)
    assert "finish" in str(error.value)


def test_changing_an_attribute_type_in_use_is_rejected():
    new_schema = [
        {**ATTRIBUTE_SCHEMA[0], "type": "number"},
        ATTRIBUTE_SCHEMA[1],
    ]

    with pytest.raises(CatalogRuleError) as error:
        validate_attribute_schema_change(
            ATTRIBUTE_SCHEMA, new_schema, [product(material="Flannel")]
        )

    assert "Frazada Jack Todos" in str(error.value)
    assert "material" in str(error.value)


def test_removing_an_attribute_in_use_is_rejected():
    new_schema = [ATTRIBUTE_SCHEMA[1]]

    with pytest.raises(CatalogRuleError) as error:
        validate_attribute_schema_change(
            ATTRIBUTE_SCHEMA, new_schema, [product(material="Flannel")]
        )

    assert "Frazada Jack Todos" in str(error.value)
    assert "material" in str(error.value)


def test_removing_an_attribute_with_a_null_value_in_use_is_rejected():
    new_schema = [ATTRIBUTE_SCHEMA[0]]

    with pytest.raises(CatalogRuleError) as error:
        validate_attribute_schema_change(
            ATTRIBUTE_SCHEMA, new_schema, [product(material="Flannel", finish=None)]
        )

    assert "Frazada Jack Todos" in str(error.value)
    assert "finish" in str(error.value)


def test_removing_an_unused_option_value_is_allowed():
    new_schema = [
        {
            "code": "size",
            "label": "Size",
            "values": [OPTION_SCHEMA[0]["values"][1]],
        }
    ]

    validate_option_schema_change(OPTION_SCHEMA, new_schema, [variant("FRZ-00012-MAX", size="MAX")])


def test_removing_an_option_value_in_use_is_rejected():
    new_schema = [
        {
            "code": "size",
            "label": "Size",
            "values": [OPTION_SCHEMA[0]["values"][0]],
        }
    ]

    with pytest.raises(CatalogRuleError) as error:
        validate_option_schema_change(OPTION_SCHEMA, new_schema, [variant(size="MAX")])

    assert "FRZ-00012-IND" in str(error.value)
    assert "MAX" in str(error.value)


def test_renaming_an_option_value_in_use_is_rejected():
    new_schema = [
        {
            "code": "size",
            "label": "Size",
            "values": [
                OPTION_SCHEMA[0]["values"][0],
                {"code": "MAXI", "label": "Maxi", "width_cm": 175, "height_cm": 160},
            ],
        }
    ]

    with pytest.raises(CatalogRuleError) as error:
        validate_option_schema_change(OPTION_SCHEMA, new_schema, [variant(size="MAX")])

    assert "FRZ-00012-IND" in str(error.value)
    assert "MAX" in str(error.value)


def test_removing_an_option_in_use_is_rejected():
    with pytest.raises(CatalogRuleError) as error:
        validate_option_schema_change(OPTION_SCHEMA, [], [variant(size="IND")])

    assert "FRZ-00012-IND" in str(error.value)
    assert "size" in str(error.value)


def test_changing_the_sku_code_is_rejected_when_variants_exist():
    with pytest.raises(CatalogRuleError) as error:
        validate_category_sku_code_change("FRZ", "FRZD", [variant(size="IND")])

    assert "FRZ-00012-IND" in str(error.value)


def test_changing_the_sku_code_is_allowed_without_variants():
    validate_category_sku_code_change("FRZ", "FRZD", [])


def test_the_same_sku_code_in_another_case_is_not_a_change():
    validate_category_sku_code_change("FRZ", "frz", [variant(size="IND")])
