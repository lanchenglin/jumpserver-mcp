from __future__ import annotations

from logging import getLogger

import httpx
from fastapi import FastAPI, Request, Response
from fastapi_mcp import FastApiMCP

from .config import settings
from .rest_api import (
    build_api_auth,
    build_base_headers,
    derive_api_base_url,
    derive_swagger_url,
    get_swagger_json,
)
from .setup import setup_logging

setup_logging(settings.log_level, debug=settings.debug)

logger = getLogger(__name__)

app = FastAPI()
base_url = derive_api_base_url(settings.api_base_url, settings.jumpserver_url)
swagger_url = derive_swagger_url(settings.swagger_url, settings.jumpserver_url)
logger.info("Fetching OpenAPI schema from API URL: %s", swagger_url)
swagger_json = get_swagger_json(swagger_url)
http_client = httpx.AsyncClient(
    auth=build_api_auth(
        api_token=settings.api_token,
        access_key_id=settings.access_key_id,
        access_key_secret=settings.access_key_secret,
    ),
    verify=False,
    headers=build_base_headers(settings.jms_org_id),
)

mcp = FastApiMCP(
    app,
    name="JumpServer API MCP",
    base_url=base_url,
    describe_all_responses=True,
    describe_full_response_schema=True,
    http_client=http_client,
    openapi_schema=swagger_json,
)

mount_path = settings.base_path.strip('"').strip("'")
if not mount_path.startswith("/"):
    mount_path = f"/{mount_path}"
mcp.mount(mount_path=mount_path)
logger.info("MCP server listening at %s", mount_path)


@app.middleware("http")
async def check_api_key(request: Request, call_next) -> Response:
    if settings.api_key:
        api_key = request.headers.get("Authorization")
        if not api_key or not api_key.startswith("Bearer ") or api_key != f"Bearer {settings.api_key}":
            logger.error("Unauthorized access attempt detected: Authorization %s", api_key)
            return Response(status_code=401, content="Unauthorized: Invalid API token")
    return await call_next(request)
