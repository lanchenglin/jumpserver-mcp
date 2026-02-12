"""This module implements the JumpServer MCP server.

It includes:
- A custom implementation of FastApiMCP for JumpServer.
- Middleware for API key validation.
- Utility classes and functions for OpenAPI schema handling.
"""

import typing
from logging import getLogger
from typing import Any, Optional
from uuid import UUID
import asyncio
import base64
import datetime
import hashlib
import hmac
import io
import json
import os
from email.utils import formatdate

import httpx
import paramiko
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi_mcp import FastApiMCP
from fastapi_mcp.openapi.convert import convert_openapi_to_mcp_tools
from fastapi_mcp.transport.sse import FastApiSseTransport
import mcp.types as types
from mcp.server.lowlevel.server import Server

from .config import settings
from .setup import setup_logging

setup_logging(settings.log_level, debug=settings.debug)

logger = getLogger(__name__)


class JumpServerOpenapiMCP(FastApiMCP):
    """A custom implementation of FastApiMCP for JumpServer.

    This class extends FastApiMCP to integrate with JumpServer's API,
    providing functionality to convert OpenAPI schemas to MCP tools,
    filter tools, and handle tool calls.

    Attributes:
        api_token: The API token used for authentication.
        swagger_json: The OpenAPI schema in JSON format.
    """

    def __init__(self, app: FastAPI, **kwargs: Any) -> None:
        api_token = kwargs.pop("api_token")
        self.api_token = api_token
        self.swagger_json = kwargs.pop("swagger_json")
        self.base_url = kwargs.pop("base_url", None)
        self.sse_transport = None
        super().__init__(app, **kwargs)

    def is_auth_session(self, session_id: str) -> bool:
        if not self.sse_transport:
            return False
        if not session_id:
            return False
        try:
            session_id = UUID(session_id)
        except ValueError:
            return False
        sse_transport = self.sse_transport
        return session_id in sse_transport._read_stream_writers

    def setup_server(self) -> None:
        """Set up the MCP server by converting OpenAPI schema to tools.

        Filter tools and register handlers for tool listing and tool calls.
        """
        # Get OpenAPI schema from FastAPI app
        openapi_schema = self.swagger_json

        # Convert OpenAPI schema to MCP tools
        all_tools, self.operation_map = convert_openapi_to_mcp_tools(
            openapi_schema,
            describe_all_responses=self._describe_all_responses,
            describe_full_response_schema=self._describe_full_response_schema,
        )
        logger.info("Loaded %d tools from OpenAPI schema.", len(all_tools))

        # Filter tools based on operation IDs and tags
        self.tools = self._filter_tools(all_tools, openapi_schema)
        logger.info("Filtered to %d tools after applying filters.", len(self.tools))

        # Normalize base URL
        self._base_url = self._base_url.removesuffix("/")

        # Create the MCP lowlevel server
        mcp_server: Server = Server(self.name, self.description)

        # Register handlers for tools
        @mcp_server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            # 在自动生成的工具基础上增加自定义 SSH 命令执行工具
            tools = list(self.tools)
            tools.append(
                types.Tool(
                    name="jumpserver_ssh_command",
                    description=(
                        "通过 JumpServer SSH 网关在指定资产上执行 shell 命令。\n"
                        "注意：这是高权限操作，请谨慎使用。"
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "asset_ip": {
                                "type": "string",
                                "description": "资产 IP，例如 192.168.1.100",
                            },
                            "system_user": {
                                "type": "string",
                                "description": "目标资产上的系统用户名，默认使用配置中的 default_system_user",
                            },
                            "command": {
                                "type": "string",
                                "description": "要执行的 shell 命令，例如 df -h",
                            },
                        },
                        "required": ["asset_ip", "command"],
                    },
                )
            )
            # SFTP 上传：将文本或 Base64 内容写入资产上的文件
            tools.append(
                types.Tool(
                    name="jumpserver_sftp_upload",
                    description=(
                        "通过 JumpServer SSH 网关使用 SFTP 将内容上传到指定资产的远程路径。\n"
                        "提供 content（文本）或 content_base64（二进制）二选一。"
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "asset_ip": {
                                "type": "string",
                                "description": "资产 IP，例如 192.168.1.100",
                            },
                            "system_user": {
                                "type": "string",
                                "description": "目标资产上的系统用户名，默认 default_system_user",
                            },
                            "remote_path": {
                                "type": "string",
                                "description": "远程文件路径，例如 /tmp/hello.txt",
                            },
                            "content": {
                                "type": "string",
                                "description": "要写入的文本内容（UTF-8）；与 content_base64 二选一",
                            },
                            "content_base64": {
                                "type": "string",
                                "description": "要写入的二进制内容（Base64 编码）；与 content 二选一",
                            },
                        },
                        "required": ["asset_ip", "remote_path"],
                    },
                )
            )
            # SFTP 下载：从资产上的远程路径读取文件内容
            tools.append(
                types.Tool(
                    name="jumpserver_sftp_download",
                    description=(
                        "通过 JumpServer SSH 网关使用 SFTP 从指定资产下载文件内容。\n"
                        "返回文本或 Base64（二进制时）。"
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "asset_ip": {
                                "type": "string",
                                "description": "资产 IP，例如 192.168.1.100",
                            },
                            "system_user": {
                                "type": "string",
                                "description": "目标资产上的系统用户名，默认 default_system_user",
                            },
                            "remote_path": {
                                "type": "string",
                                "description": "远程文件路径，例如 /etc/hostname",
                            },
                        },
                        "required": ["asset_ip", "remote_path"],
                    },
                )
            )
            # SFTP 列目录
            tools.append(
                types.Tool(
                    name="jumpserver_sftp_list",
                    description=(
                        "通过 JumpServer SSH 网关使用 SFTP 列出指定资产上某目录下的文件与子目录。"
                    ),
                    input_schema={
                        "type": "object",
                        "properties": {
                            "asset_ip": {
                                "type": "string",
                                "description": "资产 IP，例如 192.168.1.100",
                            },
                            "system_user": {
                                "type": "string",
                                "description": "目标资产上的系统用户名，默认 default_system_user",
                            },
                            "remote_path": {
                                "type": "string",
                                "description": "远程目录路径，默认 .",
                            },
                        },
                        "required": ["asset_ip"],
                    },
                )
            )
            return tools

        def _run_ssh_command(asset_ip: str, system_user: str, command: str) -> str:
            """通过 JumpServer SSH 网关执行命令的同步辅助函数。"""
            if not settings.ssh_gateway_host or not settings.ssh_gateway_username:
                raise RuntimeError("SSH 网关未配置（ssh_gateway_host / ssh_gateway_username 为空）")

            ssh_username = f"{settings.ssh_gateway_username}@{system_user}@{asset_ip}"

            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            client.connect(
                hostname=settings.ssh_gateway_host,
                port=settings.ssh_gateway_port,
                username=ssh_username,
                password=settings.ssh_gateway_password,
                look_for_keys=False,
                allow_agent=False,
                timeout=30,
            )

            stdin, stdout, stderr = client.exec_command(command)
            out = stdout.read().decode(errors="ignore")
            err = stderr.read().decode(errors="ignore")
            client.close()

            text = "STDOUT:\n" + out
            if err:
                text += "\n\nSTDERR:\n" + err
            return text

        def _open_sftp(asset_ip: str, system_user: str) -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
            """通过 JumpServer SSH 网关连接资产并打开 SFTP。返回 (ssh_client, sftp_client)，调用方负责 close。"""
            if not settings.ssh_gateway_host or not settings.ssh_gateway_username:
                raise RuntimeError("SSH 网关未配置（ssh_gateway_host / ssh_gateway_username 为空）")
            ssh_username = f"{settings.ssh_gateway_username}@{system_user}@{asset_ip}"
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=settings.ssh_gateway_host,
                port=settings.ssh_gateway_port,
                username=ssh_username,
                password=settings.ssh_gateway_password,
                look_for_keys=False,
                allow_agent=False,
                timeout=30,
            )
            sftp = client.open_sftp()
            return client, sftp

        def _sftp_makedirs(sftp: paramiko.SFTPClient, dir_path: str) -> None:
            """递归创建远程目录（若不存在）。dir_path 为绝对路径，如 /tmp/foo/bar。"""
            if not dir_path or dir_path == "." or dir_path == "/":
                return
            path = dir_path.rstrip("/")
            parts = [p for p in path.split("/") if p]
            current = ""
            for p in parts:
                current = (current + "/" + p) if current else ("/" + p)
                try:
                    sftp.stat(current)
                except OSError:
                    sftp.mkdir(current)

        def _run_sftp_upload(
            asset_ip: str,
            system_user: str,
            remote_path: str,
            content: str | None,
            content_base64: str | None,
        ) -> str:
            if not content and not content_base64:
                return "Error: content 与 content_base64 至少提供一个"
            try:
                client, sftp = _open_sftp(asset_ip, system_user)
            except Exception as e:
                return f"Error: SFTP 连接失败 - {e!s}"
            try:
                parent = os.path.dirname(remote_path)
                if parent:
                    _sftp_makedirs(sftp, parent)
                if content_base64:
                    data = base64.b64decode(content_base64)
                    sftp.putfo(io.BytesIO(data), remote_path)
                else:
                    sftp.putfo(io.BytesIO((content or "").encode("utf-8")), remote_path)
                return f"OK: 已写入 {remote_path}"
            except Exception as e:
                return f"Error: 上传失败 - {e!s}"
            finally:
                sftp.close()
                client.close()

        def _run_sftp_download(asset_ip: str, system_user: str, remote_path: str) -> str:
            try:
                client, sftp = _open_sftp(asset_ip, system_user)
            except Exception as e:
                return f"Error: SFTP 连接失败 - {e!s}"
            try:
                buf = io.BytesIO()
                sftp.getfo(remote_path, buf)
                data = buf.getvalue()
                try:
                    return data.decode("utf-8")
                except UnicodeDecodeError:
                    return "Base64:\n" + base64.b64encode(data).decode("ascii")
            except Exception as e:
                return f"Error: 下载失败 - {e!s}"
            finally:
                sftp.close()
                client.close()

        def _run_sftp_list(asset_ip: str, system_user: str, remote_path: str) -> str:
            try:
                client, sftp = _open_sftp(asset_ip, system_user)
            except Exception as e:
                return f"Error: SFTP 连接失败 - {e!s}"
            try:
                path = remote_path or "."
                attrs = sftp.listdir_attr(path)
                out = []
                for a in attrs:
                    kind = "dir" if a.st_mode and (a.st_mode & 0o170000) == 0o040000 else "file"
                    out.append({"name": a.filename, "size": a.st_size, "type": kind})
                return json.dumps(out, ensure_ascii=False, indent=2)
            except Exception as e:
                return f"Error: 列目录失败 - {e!s}"
            finally:
                sftp.close()
                client.close()

        # Register the tool call handler
        @mcp_server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict[str, Any]
        ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
            # 自定义 SSH 工具：通过 JumpServer 网关执行命令
            if name == "jumpserver_ssh_command":
                asset_ip = str(arguments.get("asset_ip", "")).strip()
                command = str(arguments.get("command", "")).strip()
                system_user = str(
                    arguments.get("system_user") or settings.default_system_user
                ).strip()

                if not asset_ip:
                    raise ValueError("asset_ip 不能为空")
                if not command:
                    raise ValueError("command 不能为空")
                if not system_user:
                    raise ValueError("system_user 不能为空")

                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(
                    None, lambda: _run_ssh_command(asset_ip, system_user, command)
                )

                return [types.TextContent(type="text", text=text)]

            if name == "jumpserver_sftp_upload":
                asset_ip = str(arguments.get("asset_ip", "")).strip()
                remote_path = str(arguments.get("remote_path", "")).strip()
                system_user = str(
                    arguments.get("system_user") or settings.default_system_user
                ).strip()
                content = arguments.get("content")
                content_base64 = arguments.get("content_base64")
                if content is not None:
                    content = str(content)
                if content_base64 is not None:
                    content_base64 = str(content_base64).strip()
                if not asset_ip:
                    raise ValueError("asset_ip 不能为空")
                if not remote_path:
                    raise ValueError("remote_path 不能为空")
                if not system_user:
                    raise ValueError("system_user 不能为空")
                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(
                    None,
                    lambda: _run_sftp_upload(
                        asset_ip, system_user, remote_path, content, content_base64
                    ),
                )
                return [types.TextContent(type="text", text=text)]

            if name == "jumpserver_sftp_download":
                asset_ip = str(arguments.get("asset_ip", "")).strip()
                remote_path = str(arguments.get("remote_path", "")).strip()
                system_user = str(
                    arguments.get("system_user") or settings.default_system_user
                ).strip()
                if not asset_ip:
                    raise ValueError("asset_ip 不能为空")
                if not remote_path:
                    raise ValueError("remote_path 不能为空")
                if not system_user:
                    raise ValueError("system_user 不能为空")
                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(
                    None, lambda: _run_sftp_download(asset_ip, system_user, remote_path)
                )
                return [types.TextContent(type="text", text=text)]

            if name == "jumpserver_sftp_list":
                asset_ip = str(arguments.get("asset_ip", "")).strip()
                remote_path = str(arguments.get("remote_path", ".")).strip() or "."
                system_user = str(
                    arguments.get("system_user") or settings.default_system_user
                ).strip()
                if not asset_ip:
                    raise ValueError("asset_ip 不能为空")
                if not system_user:
                    raise ValueError("system_user 不能为空")
                loop = asyncio.get_running_loop()
                text = await loop.run_in_executor(
                    None, lambda: _run_sftp_list(asset_ip, system_user, remote_path)
                )
                return [types.TextContent(type="text", text=text)]

            # 其他工具：继续走 OpenAPI -> HTTP 的默认逻辑
            return await self._execute_api_tool(
                client=self.http_client,
                base_url=self._base_url or "",
                tool_name=name,
                arguments=arguments,
                operation_map=self.operation_map,
            )

        self.server = mcp_server

    def mount(self, router: Optional[FastAPI | APIRouter] = None, mount_path: str = "/mcp") -> None:
        """
        Mount the MCP server to **any** FastAPI app or APIRouter.
        There is no requirement that the FastAPI app or APIRouter is the same as the one that the MCP
        server was created from.

        Args:
            router: The FastAPI app or APIRouter to mount the MCP server to. If not provided, the MCP
                    server will be mounted to the FastAPI app.
            mount_path: Path where the MCP server will be mounted
        """
        # Normalize mount path
        if not mount_path.startswith("/"):
            mount_path = f"/{mount_path}"
        if mount_path.endswith("/"):
            mount_path = mount_path[:-1]

        if not router:
            router = self.fastapi

        # Build the base path correctly for the SSE transport
        if isinstance(router, FastAPI):
            base_path = router.root_path
        elif isinstance(router, APIRouter):
            base_path = self.fastapi.root_path + router.prefix
        else:
            raise ValueError(f"Invalid router type: {type(router)}")

        messages_path = f"{base_path}{mount_path}/messages/"

        sse_transport = FastApiSseTransport(messages_path)
        self.sse_transport = sse_transport

        # Route for MCP connection
        @router.get(mount_path, include_in_schema=False, operation_id="mcp_connection")
        async def handle_mcp_connection(request: Request):
            async with sse_transport.connect_sse(request.scope, request.receive, request._send) as (
                reader,
                writer,
            ):
                authorization = request.headers.get("authorization", "")
                await self.server.run(
                    reader,
                    writer,
                    self.server.create_initialization_options(
                        notification_options=None,
                        experimental_capabilities={
                            "session_token": {"authorization": authorization},
                        },
                    ),
                )

        # Route for MCP messages
        @router.post(
            f"{mount_path}/messages/", include_in_schema=False, operation_id="mcp_messages"
        )
        async def handle_post_message(request: Request):
            return await sse_transport.handle_fastapi_post_message(request)

        # HACK: If we got a router and not a FastAPI instance, we need to re-include the router so that
        # FastAPI will pick up the new routes we added. The problem with this approach is that we assume
        # that the router is a sub-router of self.fastapi, which may not always be the case.
        #
        # TODO: Find a better way to do this.
        if isinstance(router, APIRouter):
            self.fastapi.include_router(router)

        logger.info(f"MCP server listening at {mount_path}")


class BearerAuth(httpx.Auth):
    """Allows the 'auth' argument to be passed as a token string or bytes.

    and uses HTTP Bearer authentication.
    """

    def __init__(self, token: str | bytes) -> None:
        """Initialize the BearerAuth instance with a token.

        Args:
            token (str | bytes): The token to be used for Bearer authentication.
        """
        self._auth_header = self._build_auth_header(token)

    def auth_flow(
        self, request: httpx.Request
    ) -> typing.Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = self._auth_header
        yield request

    def _build_auth_header(self, token: str | bytes) -> str:
        return f"Bearer {token}"


class JumpserverAccessKeyAuth(httpx.Auth):
    """HTTP Signature authentication using JumpServer Access Key (ID + Secret)."""

    def __init__(self, key_id: str, secret: str) -> None:
        self._key_id = key_id
        self._secret = secret.encode("utf-8")

    def auth_flow(
        self, request: httpx.Request
    ) -> typing.Generator[httpx.Request, httpx.Response, None]:
        # Ensure required headers exist: Accept + Date
        if "accept" not in request.headers:
            request.headers["Accept"] = "application/json"
        if "date" not in request.headers:
            # RFC 1123 / GMT 格式
            request.headers["Date"] = formatdate(
                timeval=None, localtime=False, usegmt=True
            )

        method = request.method.lower()

        # 获取 path + query，类似 /api/v1/users/users/?page=1
        raw_path = getattr(request.url, "raw_path", None)
        if isinstance(raw_path, (bytes, bytearray)):
            path = raw_path.decode("ascii")
        else:
            path = request.url.path
            if request.url.query:
                path = f"{path}?{request.url.query}"

        lines: list[str] = []
        lines.append(f"(request-target): {method} {path}")
        lines.append(f"accept: {request.headers['Accept']}")
        lines.append(f"date: {request.headers['Date']}")
        signing_string = "\n".join(lines)

        digest = hmac.new(
            self._secret, signing_string.encode("utf-8"), hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(digest).decode("ascii")

        headers_list = "(request-target) accept date"
        auth_header = (
            f'Signature keyId="{self._key_id}",'
            f'algorithm="hmac-sha256",'
            f'headers="{headers_list}",'
            f'signature="{signature_b64}"'
        )
        request.headers["Authorization"] = auth_header
        yield request


HTTP_OK = 200


class OpenAPISchemaFetchError(Exception):
    """Custom exception for OpenAPI schema fetch errors."""

    pass


def get_swagger_json(url: str = settings.swagger_url) -> dict[str, Any]:
    """Fetch the OpenAPI schema from the given URL.

    Args:
        url (str): The URL to fetch the OpenAPI schema from. Defaults to settings.swagger_url.

    Returns:
        dict[str, Any]: The OpenAPI schema in JSON format.

    Raises:
        OpenAPISchemaFetchError: If the schema cannot be fetched or the response status is not HTTP_OK.
    """
    kwargs = {"verify": False, "timeout": 120}

    # 优先使用 Access Key（ID + Secret）访问 swagger
    if settings.access_key_id and settings.access_key_secret:
        kwargs["auth"] = JumpserverAccessKeyAuth(
            settings.access_key_id, settings.access_key_secret
        )
    elif settings.api_token:
        # 兼容旧配置：如果提供了 api_token，则走 Bearer token
        auth = BearerAuth(settings.api_token)
        kwargs["auth"] = auth
    resp = httpx.get(url, **kwargs)
    if resp.status_code != HTTP_OK:
        error_message = f"Failed to fetch OpenAPI schema: {resp.status_code} - {resp.text}"
        raise OpenAPISchemaFetchError(error_message)
    return resp.json()


app = FastAPI()
jumpserver_url = settings.jumpserver_url
base_url = settings.api_base_url
if not base_url and jumpserver_url:
    base_url = f"{jumpserver_url}/api/v1"
    logger.info("Base API URL set to: %s", base_url)
swagger_url = settings.swagger_url
if not swagger_url and jumpserver_url:
    # swagger_url = f"{jumpserver_url}/api/docs/?format=openapi"
    swagger_url = f"{jumpserver_url}/api/swagger.json"
    logger.info("Swagger URL set to: %s", swagger_url)
logger.info("Fetching OpenAPI schema from API URL: %s", swagger_url)
swagger_json = get_swagger_json(swagger_url)

# 创建用于调用 JumpServer API 的 http 客户端
base_headers: dict[str, str] = {}
if settings.jms_org_id:
    base_headers["X-JMS-ORG"] = settings.jms_org_id

if settings.access_key_id and settings.access_key_secret:
    api_auth: httpx.Auth | None = JumpserverAccessKeyAuth(
        settings.access_key_id, settings.access_key_secret
    )
elif settings.api_token:
    api_auth = BearerAuth(settings.api_token)
else:
    api_auth = None

http_client = httpx.AsyncClient(auth=api_auth, verify=False, headers=base_headers)
mcp = JumpServerOpenapiMCP(
    app,
    name="JumpServer API MCP",
    base_url=base_url,
    describe_all_responses=True,  # Include all possible response schemas in tool descriptions
    describe_full_response_schema=True,  # Include full JSON schema in tool descriptions
    api_token=settings.api_token,
    http_client=http_client,
    swagger_json=swagger_json,
)
mount_path = settings.base_path
mount_path = mount_path.strip('"').strip("'")
if not mount_path.startswith("/"):
    mount_path = "/" + mount_path
mcp.mount(mount_path=mount_path)
mcp_path = f"{app.root_path}{mount_path}"
logger.info("Mounting MCP at path: %s", mcp_path)


@app.middleware("http")
async def check_api_key(request: Request, call_next) -> Response:
    """Middleware to check the Bearer API key in the request headers.

    This middleware validates the Bearer API key provided in the request headers.
    """
    session_id_param = request.query_params.get("session_id")
    if session_id_param:
        if mcp.is_auth_session(session_id_param):
            return await call_next(request)
        else:
            logger.error("Unauthorized access attempt detected: session_id %s", session_id_param)
            return Response(status_code=401, content="Unauthorized: Invalid session ID")
    if settings.api_key:
        api_key = request.headers.get("Authorization")
        if (
            not api_key
            or not api_key.startswith("Bearer ")
            or api_key != f"Bearer {settings.api_key}"
        ):
            logger.error("Unauthorized access attempt detected: Authorization %s", api_key)
            return Response(status_code=401, content="Unauthorized: Invalid API token")
    return await call_next(request)
