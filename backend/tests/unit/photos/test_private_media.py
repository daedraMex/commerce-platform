import pytest

from apps.photos.infrastructure.private_media import StoragePrivateMediaReader
from apps.shared.domain.store import StoreReference

HOME = StoreReference(id=1, slug="home")


@pytest.mark.parametrize(
    "key",
    [
        "stores/2/photos/previews/other.jpg",
        "stores/10/photos/previews/lookalike.jpg",
        "stores/1/../2/photos/previews/traversal.jpg",
        "/stores/1/photos/previews/absolute.jpg",
        "media/stores/1/photos/previews/wrong-root.jpg",
        "",
        None,
    ],
)
def test_the_private_reader_rejects_another_stores_or_unsafe_key(key):
    with pytest.raises(OSError):
        StoragePrivateMediaReader().open(HOME, key)
