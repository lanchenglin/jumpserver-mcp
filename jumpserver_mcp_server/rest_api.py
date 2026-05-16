from __future__ import annotations

import base64
import hashlib
import hmac
import typing
from email.utils import formatdate
from typing import Any

import httpx

from .config import settings

HTTP_OK = 200


class BearerAuth(httpx.Auth):
    def __init__(self, token: str | bytes) -> None:
        self._auth_header = f"Bearer {token}"

    def auth_flow(
        self, request: httpx.Request
    ) -> typing.Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = self._auth_header
        yield request


class JumpserverAccessKeyAuth(httpx.Auth):
    def __init__(self, key_id: str, secret: str) -> None:
        self._key_id = key_id
        self._secret = secret.encode("utf-8")

    def auth_flow(
        self, request: httpx.Request
    ) -> typing.Generator[httpx.Request, httpx.Response, None]:
        if "accept" not in request.headers:
            request.headers["Accept"] = "application/json"
        if "date" not in request.headers:
            request.headers["Date"] = formatdate(timeval=None, localtime=False, usegmt=True)

        method = request.method.lower()
        raw_path = getattr(request.url, "raw_path", None)
        if isinstance(raw_path, (bytes, bytearray)):
            path = raw_path.decode("ascii")
        else:
            path = request.url.path
            if request.url.query:
                path = f"{path}?{request.url.query}"

        signing_string = "\n".join(
            [
                f"(request-target): {method} {path}",
                f"accept: {request.headers['Accept']}",
                f"date: {request.headers['Date']}",
            ]
        )
        digest = hmac.new(self._secret, signing_string.encode("utf-8"), hashlib.sha256).digest()
        signature_b64 = base64.b64encode(digest).decode("ascii")
        request.headers["Authorization"] = (
            f'Signature keyId="{self._key_id}",'
            f'algorithm="hmac-sha256",'
            f'headers="(request-target) accept date",'
            f'signature="{signature_b64}"'
        )
        yield request


class OpenAPISchemaFetchError(Exception):
    pass


def derive_api_base_url(api_base_url: str, jumpserver_url: str) -> str:
    if api_base_url:
        return api_base_url.rstrip("/")
    return f"{jumpserver_url.rstrip('/')}/api/v1"


def derive_swagger_url(swagger_url: str, jumpserver_url: str) -> str:
    if swagger_url:
        return swagger_url
    return f"{jumpserver_url.rstrip('/')}/api/swagger.json"


def build_api_auth(
    *, api_token: str, access_key_id: str, access_key_secret: str
) -> httpx.Auth | None:
    if access_key_id and access_key_secret:
        return JumpserverAccessKeyAuth(access_key_id, access_key_secret)
    if api_token:
        return BearerAuth(api_token)
    return None


def build_base_headers(jms_org_id: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if jms_org_id:
        headers["X-JMS-ORG"] = jms_org_id
    return headers


def get_swagger_json(url: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"verify": False, "timeout": 120}
    auth = build_api_auth(
        api_token=settings.api_token,
        access_key_id=settings.access_key_id,
        access_key_secret=settings.access_key_secret,
    )
    if auth is not None:
        kwargs["auth"] = auth
    response = httpx.get(url, **kwargs)
    if response.status_code != HTTP_OK:
        raise OpenAPISchemaFetchError(
            f"Failed to fetch OpenAPI schema: {response.status_code} - {response.text}"
        )
    return response.json()
