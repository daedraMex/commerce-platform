import pytest

from apps.catalog.rules import (
    CatalogRuleError,
    validate_attribute_schema,
    validate_option_schema,
)

VALID_ATTRIBUTES = [
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

VALID_OPTIONS = [
    {
        "code": "size",
        "label": "Size",
        "values": [
            {"code": "IND", "label": "Individual", "width_cm": 110, "height_cm": 160},
            {"code": "MAX", "label": "Maxi", "width_cm": 175, "height_cm": 160},
        ],
    }
]


def test_a_valid_attribute_schema_passes():
    validate_attribute_schema(VALID_ATTRIBUTES)


def test_an_empty_attribute_schema_passes():
    validate_attribute_schema([])


def test_a_valid_option_schema_passes():
    validate_option_schema(VALID_OPTIONS)


def test_a_category_without_options_passes():
    validate_option_schema([])


@pytest.mark.parametrize(
    ("broken", "needle"),
    [
        ("not a list", "attribute schema"),
        ([{"code": "material"}], "material"),
        (
            [
                {
                    "code": "material",
                    "label": "Material",
                    "type": "string",
                    "choices": [],
                    "required": True,
                }
            ],
            "material",
        ),
        (
            [
                {
                    "code": "finish",
                    "label": "Finish",
                    "type": "choice",
                    "choices": [],
                    "required": False,
                }
            ],
            "finish",
        ),
        (
            [
                {
                    "code": "material",
                    "label": "Material",
                    "type": "text",
                    "choices": [],
                    "required": "yes",
                }
            ],
            "material",
        ),
        (
            [
                {
                    "code": "material",
                    "label": "Material",
                    "type": "text",
                    "choices": [],
                    "required": True,
                },
                {
                    "code": "material",
                    "label": "Material again",
                    "type": "text",
                    "choices": [],
                    "required": True,
                },
            ],
            "material",
        ),
    ],
)
def test_a_malformed_attribute_entry_is_rejected_naming_the_entry(broken, needle):
    with pytest.raises(CatalogRuleError) as error:
        validate_attribute_schema(broken)

    assert needle in str(error.value)


@pytest.mark.parametrize(
    ("broken", "needle"),
    [
        ("not a list", "option schema"),
        ([{"code": "size"}], "size"),
        ([{"code": "size", "label": "Size", "values": []}], "size"),
        (
            [
                {
                    "code": "size",
                    "label": "Size",
                    "values": [{"code": "IND", "label": "Individual", "width_cm": 110}],
                }
            ],
            "IND",
        ),
        (
            [
                {
                    "code": "size",
                    "label": "Size",
                    "values": [
                        {
                            "code": "IND",
                            "label": "Individual",
                            "width_cm": 0,
                            "height_cm": 160,
                        }
                    ],
                }
            ],
            "IND",
        ),
        (
            [
                {
                    "code": "size",
                    "label": "Size",
                    "values": [
                        {
                            "code": "IND",
                            "label": "Individual",
                            "width_cm": 110,
                            "height_cm": 160,
                        },
                        {
                            "code": "IND",
                            "label": "Individual again",
                            "width_cm": 120,
                            "height_cm": 160,
                        },
                    ],
                }
            ],
            "IND",
        ),
        (
            [
                {
                    "code": "size",
                    "label": "Size",
                    "values": [
                        {
                            "code": "IND",
                            "label": "Individual",
                            "width_cm": 110,
                            "height_cm": 160,
                        },
                    ],
                },
                {
                    "code": "size",
                    "label": "Size again",
                    "values": [
                        {
                            "code": "MAX",
                            "label": "Maxi",
                            "width_cm": 175,
                            "height_cm": 160,
                        }
                    ],
                },
            ],
            "size",
        ),
    ],
)
def test_a_malformed_option_entry_is_rejected_naming_the_entry(broken, needle):
    with pytest.raises(CatalogRuleError) as error:
        validate_option_schema(broken)

    assert needle in str(error.value)


def test_a_non_size_option_needs_no_dimensions():
    validate_option_schema(
        [
            {
                "code": "color",
                "label": "Color",
                "values": [{"code": "RED", "label": "Red"}],
            }
        ]
    )
