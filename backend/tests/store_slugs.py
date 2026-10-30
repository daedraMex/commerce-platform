"""Store slug corpus shared by the domain and API tests."""

VALID_STORE_SLUGS = [
    "anime",
    "home",
    "a",
    "a" * 50,
    "anime-store-2",
    "2-store",
]

INVALID_STORE_SLUGS = [
    "",
    "Anime",
    " anime",
    "anime ",
    "-anime",
    "anime-",
    "anime--store",
    "anime_store",
    "a" * 51,
    "anime\n",
    "anime store",
]
