"""Mint the GitHub App installation token used for write operations.

The token is minted on demand (never at startup, never stored) and passed only
to the push and pull-request subprocesses, scoped to those calls. The OpenCode
subprocess never sees it.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Protocol
from urllib import request
from urllib.error import HTTPError, URLError

import jwt

from .config import FactoryConfigError


class TokenProvider(Protocol):
    def mint(self, repo: str) -> str: ...


SignFn = Callable[[dict, str], str]
PostFn = Callable[[str, dict], dict]


def _default_sign(payload: dict, private_key: str) -> str:
    return jwt.encode(payload, private_key, algorithm="RS256")


def _default_post(url: str, headers: dict) -> dict:
    req = request.Request(url, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (URLError, HTTPError) as exc:
        raise RuntimeError(f"failed to mint the GitHub installation token: {exc}") from exc


class GithubAppTokenProvider:
    def __init__(
        self,
        *,
        app_id: str | None,
        private_key: str | None,
        installation_id: str | None,
        api_url: str = "https://api.github.com",
        clock: Callable[[], float] = time.time,
        sign: SignFn = _default_sign,
        post: PostFn = _default_post,
    ):
        self._app_id = app_id
        self._private_key = private_key
        self._installation_id = installation_id
        self._api_url = api_url.rstrip("/")
        self._clock = clock
        self._sign = sign
        self._post = post

    def mint(self, repo: str) -> str:
        del repo  # an installation token covers the whole installation, not one repo
        if not (self._app_id and self._private_key and self._installation_id):
            raise FactoryConfigError(
                "XOLO_BOT_APP_ID, XOLO_BOT_PRIVATE_KEY and XOLO_BOT_INSTALLATION_ID "
                "must all be set to mint the xolo-bot installation token."
            )
        now = int(self._clock())
        token_jwt = self._sign(
            {"iat": now - 60, "exp": now + 540, "iss": self._app_id},
            self._private_key,
        )
        url = f"{self._api_url}/app/installations/{self._installation_id}/access_tokens"
        headers = {
            "Authorization": f"Bearer {token_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = self._post(url, headers)
        token = response.get("token")
        if not token:
            raise RuntimeError("GitHub returned no installation token.")
        return token
