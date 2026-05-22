from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from logging import getLogger
from typing import Any

import httpx
from mcp.server.lowlevel.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import settings
from .connection_pool import SSHConnectionPool
from .rest_api import (
    build_api_auth,
    build_base_headers,
    derive_api_base_url,
    derive_swagger_url,
    get_swagger_json,
)
from .setup import setup_logging
from .tools import CommandPolicy, create_tools

setup_logging(settings.log_level, debug=settings.debug)

logger = getLogger(__name__)

base_url = derive_api_base_url(settings.api_base_url, settings.jumpserver_url)
swagger_url = derive_swagger_url(settings.swagger_url, settings.jumpserver_url)

# --- SSH/SFTP 连接池 ---
ssh_pool = SSHConnectionPool(
    gateway_host=settings.ssh_gateway_host,
    gateway_port=settings.ssh_gateway_port,
    gateway_username=settings.ssh_gateway_username,
    gateway_password=settings.ssh_gateway_password,
    gateway_private_key_path=settings.ssh_gateway_private_key_path,
    gateway_known_hosts_path=settings.ssh_gateway_known_hosts_path,
    connect_timeout=settings.ssh_connect_timeout,
    max_connections=settings.ssh_pool_max_connections,
    idle_timeout=settings.ssh_pool_idle_timeout,
    health_check_interval=settings.ssh_health_check_interval,
)

command_patterns = [
    pattern.strip()
    for pattern in settings.ssh_command_policy_patterns.split(",")
    if pattern.strip()
]
tool_impl = create_tools(
    ssh_pool,
    default_system_user=settings.default_system_user,
    command_timeout=settings.ssh_command_timeout,
    command_policy=CommandPolicy(
        mode=settings.ssh_command_policy_mode.lower(),
        patterns=command_patterns,
    ),
    max_command_output_bytes=settings.max_command_output_bytes,
    max_sftp_upload_bytes=settings.max_sftp_upload_bytes,
    max_sftp_download_bytes=settings.max_sftp_download_bytes,
    max_sftp_list_entries=settings.max_sftp_list_entries,
)

tool_executor = ThreadPoolExecutor(
    max_workers=settings.mcp_worker_threads, thread_name_prefix="mcp-tool"
)


# --- OpenAPI 解析工具 ---

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


def _build_inputSchema(
    operation: dict[str, Any], openapi_params: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the MCP tool input schema from OpenAPI operation params + body."""
    path_params, query_params, param_schema = _extract_params(
        operation.get("path", ""), openapi_params
    )
    body_props, body_required = _extract_body_schema(operation)

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
    swagger: dict[str, Any], mcp_server: Server, client: httpx.AsyncClient, base: str
) -> list[types.Tool]:
    """Parse an OpenAPI/Swagger spec and return MCP tool definitions + register handlers."""
    paths = swagger.get("paths", {})
    rest_tools: list[types.Tool] = []

    for path, path_item in paths.items():
        shared_params = _get_all_params(path_item)
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if not operation:
                continue

            operation_id = operation.get("operationId")
            if not operation_id:
                clean = re.sub(r"[^a-zA-Z0-9]", "_", path)
                operation_id = f"{method}_{clean}".strip("_")

            tool_name = re.sub(r"[^a-zA-Z0-9_]", "_", operation_id).strip("_")
            tool_name = re.sub(r"_+", "_", tool_name)

            op_params = operation.get("parameters", [])
            merged_params = shared_params + op_params

            path_params, query_params, param_schema = _extract_params(path, merged_params)
            body_props, body_required = _extract_body_schema(operation)

            all_properties = {**param_schema.get("properties", {}), **body_props}
            all_required = list(set(param_schema.get("required", []) + body_required))
            inputSchema = {
                "type": "object",
                "properties": all_properties,
                "required": all_required,
            }

            description = _build_tool_description(operation, method, path)

            fn = _make_tool_fn(method, path, path_params, query_params, body_props, client, base)

            rest_tools.append(types.Tool(name=tool_name, description=description, inputSchema=inputSchema))

            # Register call handler
            _rest_tool_handlers[tool_name] = fn

    logger.info("Registered %d REST API tools from OpenAPI schema", len(rest_tools))
    return rest_tools


# Registry for REST API tool call handlers
_rest_tool_handlers: dict[str, Callable] = {}


# --- SSH/SFTP 工具定义 ---

SSH_TOOLS: list[types.Tool] = [
    types.Tool(
        name="jumpserver_ssh_command",
        description="通过 JumpServer SSH 网关在指定资产上执行 shell 命令。",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_ip": {"type": "string", "description": "资产 IP，例如 192.168.1.100"},
                "system_user": {
                    "type": "string",
                    "description": "目标资产上的系统用户名，默认使用配置中的 default_system_user",
                },
                "command": {"type": "string", "description": "要执行的 shell 命令，例如 df -h"},
            },
            "required": ["asset_ip", "command"],
        },
    ),
    types.Tool(
        name="jumpserver_sftp_upload",
        description="通过 JumpServer SSH 网关使用 SFTP 将内容上传到指定资产的远程路径。",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_ip": {"type": "string", "description": "资产 IP，例如 192.168.1.100"},
                "system_user": {
                    "type": "string",
                    "description": "目标资产上的系统用户名，默认 default_system_user",
                },
                "remote_path": {"type": "string", "description": "远程文件路径，例如 /tmp/hello.txt"},
                "content": {
                    "type": "string",
                    "description": "要写入的文本内容（UTF-8）；与 content_base64 二选一",
                },
                "content_base64": {
                    "type": "string",
                    "description": "要写入的二进制内容（Base64 编码）；与 content_base64 二选一",
                },
            },
            "required": ["asset_ip", "remote_path"],
        },
    ),
    types.Tool(
        name="jumpserver_sftp_download",
        description="通过 JumpServer SSH 网关使用 SFTP 从指定资产下载文件内容。",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_ip": {"type": "string", "description": "资产 IP，例如 192.168.1.100"},
                "system_user": {
                    "type": "string",
                    "description": "目标资产上的系统用户名，默认 default_system_user",
                },
                "remote_path": {"type": "string", "description": "远程文件路径，例如 /etc/hostname"},
            },
            "required": ["asset_ip", "remote_path"],
        },
    ),
    types.Tool(
        name="jumpserver_sftp_list",
        description="通过 JumpServer SSH 网关使用 SFTP 列出指定资产上某目录下的文件与子目录。",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_ip": {"type": "string", "description": "资产 IP，例如 192.168.1.100"},
                "system_user": {
                    "type": "string",
                    "description": "目标资产上的系统用户名，默认 default_system_user",
                },
                "remote_path": {"type": "string", "description": "远程目录路径，默认 ."},
            },
            "required": ["asset_ip"],
        },
    ),
]

SSH_TOOL_NAMES = {t.name for t in SSH_TOOLS}


# --- MCP Server ---

mount_path = settings.base_path.strip('"').strip("'")
if not mount_path.startswith("/"):
    mount_path = f"/{mount_path}"
mount_path = mount_path.rstrip("/") or "/sse"
messages_path = f"{mount_path}/messages/"

mcp_server = Server("JumpServer MCP")
sse_transport = SseServerTransport(messages_path)


@mcp_server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    tools = list(SSH_TOOLS)
    tools.extend(_rest_api_tools)
    return tools


@mcp_server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    # SSH/SFTP tools
    if name in SSH_TOOL_NAMES:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            tool_executor, lambda: tool_impl.call(name, arguments)
        )
        return [types.TextContent(type="text", text=text)]

    # REST API tools
    handler = _rest_tool_handlers.get(name)
    if handler is not None:
        result = await handler(**arguments)
        return [types.TextContent(type="text", text=result)]

    return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


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

    global _rest_api_tools
    _rest_api_tools = parse_swagger_to_tools(swagger_json, mcp_server, http_client, base_url)

    @asynccontextmanager
    async def lifespan(_: Starlette):
        try:
            yield
        finally:
            ssh_pool.close_all()
            tool_executor.shutdown(wait=False, cancel_futures=True)
            await http_client.aclose()

    from starlette.routing import Mount, Route

    starlette = Starlette(
        lifespan=lifespan,
        routes=[
            Route(mount_path, _sse_handler, methods=["GET"]),
            Mount(messages_path, app=sse_transport.handle_post_message),
        ],
    )

    if settings.api_key:

        class ApiKeyMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next: Callable) -> Response:
                auth_header = request.headers.get("Authorization", "")
                if auth_header != f"Bearer {settings.api_key}":
                    return Response(status_code=401, content="Unauthorized")
                return await call_next(request)

        starlette.add_middleware(ApiKeyMiddleware)

    logger.info(
        "MCP server listening at %s — %d SSH/SFTP tools + %d REST API tools",
        mount_path,
        len(SSH_TOOLS),
        len(_rest_api_tools),
    )
    return starlette


async def _sse_handler(request: Request) -> Response:
    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )
    return Response()


_rest_api_tools: list[types.Tool] = []

app = create_app()
