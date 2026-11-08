import pytest

from factory.config import FactoryConfigError
from factory.credentials import GithubAppTokenProvider


def test_mint_returns_token_and_uses_bearer_jwt():
    posts = []

    def sign(payload, private_key):
        return f"JWT-{payload['iss']}"

    def post(url, headers):
        posts.append((url, headers))
        return {"token": "ghs_install_123"}

    provider = GithubAppTokenProvider(
        app_id="42",
        private_key="-----BEGIN PRIVATE KEY-----",
        installation_id="7",
        clock=lambda: 1_000_000,
        sign=sign,
        post=post,
    )

    token = provider.mint("daedraMex/commerce-platform")

    assert token == "ghs_install_123"
    url, headers = posts[0]
    assert url.endswith("/app/installations/7/access_tokens")
    assert headers["Authorization"] == "Bearer JWT-42"


def test_mint_fails_clearly_when_credentials_missing():
    provider = GithubAppTokenProvider(app_id=None, private_key=None, installation_id=None)
    with pytest.raises(FactoryConfigError, match="XOLO_BOT_APP_ID"):
        provider.mint("r")


def test_mint_raises_when_no_token_in_response():
    provider = GithubAppTokenProvider(
        app_id="1",
        private_key="k",
        installation_id="2",
        sign=lambda p, k: "jwt",
        post=lambda url, headers: {},
    )
    with pytest.raises(RuntimeError, match="no installation token"):
        provider.mint("r")
