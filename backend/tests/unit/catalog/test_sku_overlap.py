from apps.catalog.rules import OtherCategory, find_sku_conflicts, sku_suffixes


def size_option(*values):
    return [
        {
            "code": "size",
            "label": "Size",
            "values": [
                {
                    "code": code,
                    "label": label,
                    "width_cm": width,
                    "height_cm": height,
                }
                for code, label, width, height in values
            ],
        }
    ]


def donut():
    return size_option(("DON-80", "Donut", 80, 80))


def rectangular():
    return size_option(
        ("REC-45X35", "Rectangular 45 x 35", 45, 35),
        ("REC-50X120", "Abrazable", 50, 120),
    )


def test_different_suffixes_under_the_same_sku_code_are_accepted():
    others = [OtherCategory("Almohada rectangular", "ALM", rectangular())]

    conflicts = find_sku_conflicts(sku_code="ALM", option_schema=donut(), others=others)

    assert conflicts == ()


def test_a_value_code_repeated_under_the_same_sku_code_is_rejected():
    others = [OtherCategory("Almohada dona", "ALM", donut())]

    conflicts = find_sku_conflicts(sku_code="ALM", option_schema=donut(), others=others)

    assert len(conflicts) == 1
    assert conflicts[0].category == "Almohada dona"
    assert conflicts[0].codes == ("DON-80",)


def test_two_categories_without_options_under_the_same_sku_code_are_rejected():
    others = [OtherCategory("Frazada", "ALM", [])]

    conflicts = find_sku_conflicts(sku_code="ALM", option_schema=[], others=others)

    assert len(conflicts) == 1
    assert conflicts[0].category == "Frazada"
    assert conflicts[0].codes == ("",)


def test_sku_codes_are_compared_ignoring_case():
    others = [OtherCategory("Almohada dona", "alm", donut())]

    conflicts = find_sku_conflicts(sku_code="ALM", option_schema=donut(), others=others)

    assert len(conflicts) == 1
    assert conflicts[0].category == "Almohada dona"


def test_the_same_value_codes_under_different_sku_codes_are_accepted():
    others = [OtherCategory("Frazada", "FRZ", donut())]

    conflicts = find_sku_conflicts(sku_code="ALM", option_schema=donut(), others=others)

    assert conflicts == ()


def test_suffixes_combine_every_option_in_order():
    options = [
        {
            "code": "size",
            "label": "Size",
            "values": [{"code": "IND", "label": "Individual", "width_cm": 110, "height_cm": 160}],
        },
        {
            "code": "color",
            "label": "Color",
            "values": [
                {"code": "RED", "label": "Red"},
                {"code": "BLUE", "label": "Blue"},
            ],
        },
    ]

    assert sku_suffixes(options) == frozenset({"IND-RED", "IND-BLUE"})


def test_a_category_without_options_has_one_empty_suffix():
    assert sku_suffixes([]) == frozenset({""})
