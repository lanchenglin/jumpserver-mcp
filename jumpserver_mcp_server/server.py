from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from logging import getLogger
from typing import Any

from mcp.server.lowlevel.server import Server
from mcp.server.sse import SseServerTransport
import mcp.types as types
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .config import settings
from .connection_pool import SSHConnectionPool
from .setup import setup_logging
from .tools import CommandPolicy, create_tools

setup_logging(settings.log_level, debug=settings.debug)

logger = getLogger(__name__)

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


# --- SSH/SFTP 工具定义 ---

SSH_TOOLS: list[types.Tool] = [
    types.Tool(
        name="jumpserver_check_host",
        description="检查指定资产主机是否可达（通过 SSH 网关连接测试）。",
        inputSchema={
            "type": "object",
            "properties": {
                "asset_ip": {"type": "string", "description": "资产 IP，例如 192.168.1.100"},
                "system_user": {
                    "type": "string",
                    "description": "目标资产上的系统用户名，默认使用配置中的 default_system_user",
                },
            },
            "required": ["asset_ip"],
        },
    ),
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
    return list(SSH_TOOLS)


@mcp_server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if name in SSH_TOOL_NAMES:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(
            tool_executor, lambda: tool_impl.call(name, arguments)
        )
        return [types.TextContent(type="text", text=text)]

    return [types.TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]


def create_app() -> Starlette:
    @asynccontextmanager
    async def lifespan(_: Starlette):
        try:
            yield
        finally:
            ssh_pool.close_all()
            tool_executor.shutdown(wait=False, cancel_futures=True)

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
        "MCP server listening at %s — %d tools (SSH/SFTP only)",
        mount_path,
        len(SSH_TOOLS),
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


app = create_app()
