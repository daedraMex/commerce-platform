from apps.catalog.rules import slugify


def test_slugs_are_lowercase_without_accents():
    assert slugify("Frazada Térmica") == "frazada-termica"


def test_slugs_remove_every_kind_of_accent():
    assert slugify("Ñandú Ámbar") == "nandu-ambar"


def test_slugs_join_words_with_single_hyphens():
    assert slugify("  Almohada   dona  ") == "almohada-dona"


def test_slugs_drop_punctuation():
    assert slugify("Ámbar & Co.") == "ambar-co"


def test_a_name_without_letters_or_digits_becomes_an_empty_slug():
    assert slugify("!!!") == ""
