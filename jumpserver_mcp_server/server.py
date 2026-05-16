from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from logging import getLogger
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount

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

base_url = derive_api_base_url(settings.api_base_url, settings.jumpserver_url)
swagger_url = derive_swagger_url(settings.swagger_url, settings.jumpserver_url)


def _extract_params(
    path: str, openapi_params: list[dict[str, Any]]
) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    """Extract path parameters, query parameters and their schemas from OpenAPI spec."""
    path_params = []
    query_params: dict[str, str] = {}
    properties: dict[str, Any] = {}
    required_fields: list[str] = []

    for p in openapi_params:
        name = p["name"]
        p_in = p.get("in", "query")
        if p_in == "path" and "{" in path:
            path_params.append(name)
        elif p_in == "query":
            query_params[name] = "str"
        schema = p.get("schema", {"type": "string"})
        properties[name] = schema
        if p.get("required"):
            required_fields.append(name)

    return path_params, query_params, {"type": "object", "properties": properties, "required": required_fields}


def _extract_body_schema(operation: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Extract request body schema from an OpenAPI operation."""
    body = operation.get("requestBody")
    if not body:
        return {}, []

    content = body.get("content", {})
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})
    if not schema:
        return {}, []

    properties = schema.get("properties", {})
    required = schema.get("required", [])
    return properties, required


def _build_input_schema(
    operation: dict[str, Any], openapi_params: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the MCP tool input schema from OpenAPI operation params + body."""
    path_params, query_params, param_schema = _extract_params(
        operation.get("path", ""), openapi_params
    )
    body_props, body_required = _extract_body_schema(operation)

    # Merge into a single schema
    all_properties = {**param_schema.get("properties", {}), **body_props}
    all_required = list(set(param_schema.get("required", []) + body_required))

    return {
        "type": "object",
        "properties": all_properties,
        "required": all_required,
    }


def _build_tool_description(operation: dict[str, Any], method: str, path: str) -> str:
    """Build a human-readable description for an MCP tool."""
    summary = operation.get("summary", "")
    desc = operation.get("description", "")
    parts = [f"{method.upper()} {path}"]
    if summary:
        parts.append(summary)
    if desc:
        parts.append(desc)
    return " | ".join(parts)


def _get_all_params(path_item: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect parameters from path level and merge with operation level."""
    return path_item.get("parameters", [])


def _make_tool_fn(
    method: str,
    path_template: str,
    path_params: list[str],
    query_params: dict[str, str],
    body_props: dict[str, Any],
    client: httpx.AsyncClient,
    base: str,
) -> Callable:
    """Create an async function that proxies a call to JumpServer."""

    async def _call(**kwargs: Any) -> str:
        url_path = path_template
        query_dict: dict[str, str] = {}
        body_dict: dict[str, Any] = {}

        for key, value in kwargs.items():
            if key in path_params:
                url_path = url_path.replace(f"{{{key}}}", str(value))
            elif key in query_params:
                query_dict[key] = str(value)
            elif key in body_props:
                body_dict[key] = value

        url = f"{base}{url_path}"
        send_kwargs: dict[str, Any] = {}
        if query_dict:
            send_kwargs["params"] = query_dict
        if body_dict and method in ("post", "put", "patch"):
            send_kwargs["json"] = body_dict

        try:
            response = await getattr(client, method)(url, **send_kwargs)
            try:
                return json.dumps(response.json(), ensure_ascii=False, indent=2)
            except Exception:
                return response.text
        except httpx.HTTPError as e:
            return json.dumps({"error": str(e)})

    return _call


def parse_swagger_to_tools(
    swagger: dict[str, Any], mcp_server: FastMCP, client: httpx.AsyncClient, base: str
) -> None:
    """Parse an OpenAPI/Swagger spec and register each operation as an MCP tool."""
    paths = swagger.get("paths", {})
    registered = 0

    for path, path_item in paths.items():
        shared_params = _get_all_params(path_item)
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if not operation:
                continue

            operation_id = operation.get("operationId")
            if not operation_id:
                # Generate a stable operation ID
                clean = re.sub(r"[^a-zA-Z0-9]", "_", path)
                operation_id = f"{method}_{clean}".strip("_")

            # Sanitize tool name (MCP tools need valid identifiers)
            tool_name = re.sub(r"[^a-zA-Z0-9_]", "_", operation_id).strip("_")
            # Deduplicate consecutive underscores
            tool_name = re.sub(r"_+", "_", tool_name)

            # Merge shared + operation params
            op_params = operation.get("parameters", [])
            merged_params = shared_params + op_params

            path_params, query_params, param_schema = _extract_params(path, merged_params)
            body_props, body_required = _extract_body_schema(operation)

            # Build input schema
            all_properties = {**param_schema.get("properties", {}), **body_props}
            all_required = list(set(param_schema.get("required", []) + body_required))
            input_schema = {
                "type": "object",
                "properties": all_properties,
                "required": all_required,
            }

            # Description
            description = _build_tool_description(operation, method, path)

            # Create proxy function
            fn = _make_tool_fn(method, path, path_params, query_params, body_props, client, base)

            # Register as MCP tool
            mcp_server.add_tool(fn, name=tool_name, description=description)
            registered += 1

    logger.info("Registered %d MCP tools from OpenAPI schema", registered)


def create_app() -> Starlette:
    """Build and return the full Starlette application."""
    logger.info("Fetching OpenAPI schema from %s", swagger_url)
    swagger_json = get_swagger_json(swagger_url)

    http_client = httpx.AsyncClient(
        auth=build_api_auth(
            api_token=settings.api_token,
            access_key_id=settings.access_key_id,
            access_key_secret=settings.access_key_secret,
        ),
        verify=False,
        headers=build_base_headers(settings.jms_org_id),
        timeout=120,
    )

    mcp_server = FastMCP(name="JumpServer API MCP")

    parse_swagger_to_tools(swagger_json, mcp_server, http_client, base_url)

    mount_path = settings.base_path.strip('"').strip("'")
    if not mount_path.startswith("/"):
        mount_path = f"/{mount_path}"

    sse_app = mcp_server.sse_app()
    # Merge sse_app routes into our root app so /sse and /messages work at top level
    routes = list(sse_app.routes)

    starlette = Starlette(routes=routes)

    if settings.api_key:

        class ApiKeyMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next: Callable) -> Response:
                auth_header = request.headers.get("Authorization", "")
                if auth_header != f"Bearer {settings.api_key}":
                    return Response(status_code=401, content="Unauthorized")
                return await call_next(request)

        starlette.add_middleware(ApiKeyMiddleware)

    logger.info("MCP server listening at %s", mount_path)
    return starlette


app = create_app()
