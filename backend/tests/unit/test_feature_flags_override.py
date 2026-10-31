from apps.shared.domain.store import StoreReference
from config.dependencies import get_feature_flags


class EverythingOn:
    def is_enabled(self, store, code):
        return True


def test_a_fixture_backs_get_feature_flags_with_a_fake_without_the_database(
    override_feature_flags,
):
    override_feature_flags(EverythingOn())

    assert get_feature_flags().is_enabled(StoreReference(id=1, slug="home"), "any-flag") is True
