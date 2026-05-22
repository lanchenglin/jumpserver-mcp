from __future__ import annotations

import base64
import binascii
import fnmatch
import json
import shlex
import stat
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol


class ToolErrorCode(str, Enum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    COMMAND_BLOCKED = "COMMAND_BLOCKED"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    exit_status: int | None = None

    @property
    def output(self) -> str:
        text = "STDOUT:\n" + self.stdout
        if self.stderr:
            text += "\n\nSTDERR:\n" + self.stderr
        return text


@dataclass(frozen=True)
class CommandPolicy:
    mode: str = "none"
    patterns: list[str] | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"none", "blacklist", "whitelist"}:
            raise ValueError("ssh_command_policy_mode 必须是 none、blacklist 或 whitelist")

    def allows(self, command: str) -> bool:
        patterns = self.patterns or []
        if self.mode == "none":
            return True
        if self.mode == "whitelist" and _has_shell_control_operator(command):
            return False
        matched = any(fnmatch.fnmatch(command, pattern) for pattern in patterns)
        if self.mode == "whitelist":
            return matched
        return not matched


class ConnectionPool(Protocol):
    def run_command(
        self, asset_ip: str, system_user: str, command: str, timeout: int | None = None
    ) -> CommandResult: ...

    def upload(self, asset_ip: str, system_user: str, remote_path: str, data: bytes) -> None: ...

    def download(
        self, asset_ip: str, system_user: str, remote_path: str, max_bytes: int | None = None
    ) -> bytes: ...

    def list_dir(
        self, asset_ip: str, system_user: str, remote_path: str, limit: int | None = None
    ) -> list[Any]: ...


def build_tool_result(
    success: bool,
    message: str,
    *,
    code: str = "OK",
    data: dict[str, Any] | list[Any] | None = None,
) -> str:
    payload = {
        "success": success,
        "error": None if success else message,
        "code": code,
        "message": message,
        "data": data if data is not None else {},
    }
    return json.dumps(payload, ensure_ascii=False)


@dataclass
class JumpServerTools:
    pool: ConnectionPool
    default_system_user: str
    command_timeout: int
    command_policy: CommandPolicy
    max_command_output_bytes: int
    max_sftp_upload_bytes: int
    max_sftp_download_bytes: int
    max_sftp_list_entries: int

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        try:
            if name == "jumpserver_check_host":
                return self._check_host(arguments)
            if name == "jumpserver_ssh_command":
                return self._ssh_command(arguments)
            if name == "jumpserver_sftp_upload":
                return self._sftp_upload(arguments)
            if name == "jumpserver_sftp_download":
                return self._sftp_download(arguments)
            if name == "jumpserver_sftp_list":
                return self._sftp_list(arguments)
            return build_tool_result(
                False,
                f"未知工具: {name}",
                code=ToolErrorCode.UNKNOWN_TOOL.value,
            )
        except PayloadTooLargeError as exc:
            return build_tool_result(False, str(exc), code=ToolErrorCode.PAYLOAD_TOO_LARGE.value)
        except ValueError as exc:
            return build_tool_result(False, str(exc), code=ToolErrorCode.INVALID_ARGUMENT.value)
        except ConnectionError as exc:
            return build_tool_result(False, str(exc), code=ToolErrorCode.CONNECTION_ERROR.value)
        except Exception as exc:
            return build_tool_result(False, str(exc), code=ToolErrorCode.EXECUTION_ERROR.value)

    def _common(self, arguments: dict[str, Any]) -> tuple[str, str]:
        asset_ip = str(arguments.get("asset_ip", "")).strip()
        system_user = str(arguments.get("system_user") or self.default_system_user).strip()
        if not asset_ip:
            raise ValueError("asset_ip 不能为空")
        if not system_user:
            raise ValueError("system_user 不能为空")
        if _has_ssh_username_separator(asset_ip):
            raise ValueError("asset_ip 不能包含 @ 或空白字符")
        if _has_ssh_username_separator(system_user):
            raise ValueError("system_user 不能包含 @ 或空白字符")
        return asset_ip, system_user

    def _check_host(self, arguments: dict[str, Any]) -> str:
        asset_ip, system_user = self._common(arguments)
        try:
            result = self.pool.run_command(asset_ip, system_user, "echo ok", timeout=10)
            reachable = result.exit_status == 0 and "ok" in result.stdout
        except Exception:
            reachable = False
        return build_tool_result(
            True,
            "OK",
            data={"asset_ip": asset_ip, "system_user": system_user, "reachable": reachable},
        )

    def _ssh_command(self, arguments: dict[str, Any]) -> str:
        asset_ip, system_user = self._common(arguments)
        command = str(arguments.get("command", "")).strip()
        if not command:
            raise ValueError("command 不能为空")
        if not self.command_policy.allows(command):
            return build_tool_result(
                False,
                "命令被策略阻止",
                code=ToolErrorCode.COMMAND_BLOCKED.value,
            )

        result = self.pool.run_command(asset_ip, system_user, command, timeout=self.command_timeout)
        stdout, stdout_truncated = _truncate_text(result.stdout, self.max_command_output_bytes)
        stderr, stderr_truncated = _truncate_text(result.stderr, self.max_command_output_bytes)
        display = CommandResult(stdout=stdout, stderr=stderr, exit_status=result.exit_status)
        return build_tool_result(
            True,
            "OK",
            data={
                "stdout": stdout,
                "stderr": stderr,
                "output": display.output,
                "exit_status": result.exit_status,
                "truncated": stdout_truncated or stderr_truncated,
            },
        )

    def _sftp_upload(self, arguments: dict[str, Any]) -> str:
        asset_ip, system_user = self._common(arguments)
        remote_path = str(arguments.get("remote_path", "")).strip()
        content = arguments.get("content")
        content_base64 = arguments.get("content_base64")
        if not remote_path:
            raise ValueError("remote_path 不能为空")
        if content is None and content_base64 is None:
            raise ValueError("content 与 content_base64 至少提供一个")
        if content_base64 is not None:
            try:
                data = base64.b64decode(str(content_base64).strip(), validate=True)
            except binascii.Error as exc:
                raise ValueError("content_base64 不是有效的 Base64") from exc
        else:
            data = str(content).encode("utf-8")
        if len(data) > self.max_sftp_upload_bytes:
            raise PayloadTooLargeError("上传内容超过 max_sftp_upload_bytes 限制")
        self.pool.upload(asset_ip, system_user, remote_path, data)
        return build_tool_result(
            True,
            "OK",
            data={"remote_path": remote_path, "bytes": len(data)},
        )

    def _sftp_download(self, arguments: dict[str, Any]) -> str:
        asset_ip, system_user = self._common(arguments)
        remote_path = str(arguments.get("remote_path", "")).strip()
        if not remote_path:
            raise ValueError("remote_path 不能为空")
        data = self.pool.download(
            asset_ip, system_user, remote_path, max_bytes=self.max_sftp_download_bytes
        )
        try:
            payload = {"remote_path": remote_path, "encoding": "text", "content": data.decode("utf-8")}
        except UnicodeDecodeError:
            payload = {
                "remote_path": remote_path,
                "encoding": "base64",
                "content": base64.b64encode(data).decode("ascii"),
            }
        return build_tool_result(True, "OK", data=payload)

    def _sftp_list(self, arguments: dict[str, Any]) -> str:
        asset_ip, system_user = self._common(arguments)
        remote_path = str(arguments.get("remote_path", ".")).strip() or "."
        attrs = self.pool.list_dir(
            asset_ip, system_user, remote_path, limit=self.max_sftp_list_entries + 1
        )
        truncated = len(attrs) > self.max_sftp_list_entries
        entries = []
        for attr in attrs[: self.max_sftp_list_entries]:
            mode = getattr(attr, "st_mode", 0) or 0
            entries.append(
                {
                    "name": attr.filename,
                    "size": attr.st_size,
                    "type": "dir" if stat.S_ISDIR(mode) else "file",
                }
            )
        return build_tool_result(
            True,
            "OK",
            data={"remote_path": remote_path, "entries": entries, "truncated": truncated},
        )


def _has_ssh_username_separator(value: str) -> bool:
    return "@" in value or any(char.isspace() for char in value)


def _has_shell_control_operator(command: str) -> bool:
    if "$" in command:
        return True
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|`")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return True
    return any(token in {";", "&&", "||", "|", "&", "`"} for token in tokens)


def create_tools(
    pool: ConnectionPool,
    *,
    default_system_user: str,
    command_timeout: int,
    command_policy: CommandPolicy | None = None,
    max_command_output_bytes: int = 1_048_576,
    max_sftp_upload_bytes: int = 10_485_760,
    max_sftp_download_bytes: int = 10_485_760,
    max_sftp_list_entries: int = 1000,
) -> JumpServerTools:
    return JumpServerTools(
        pool=pool,
        default_system_user=default_system_user,
        command_timeout=command_timeout,
        command_policy=command_policy or CommandPolicy(),
        max_command_output_bytes=max_command_output_bytes,
        max_sftp_upload_bytes=max_sftp_upload_bytes,
        max_sftp_download_bytes=max_sftp_download_bytes,
        max_sftp_list_entries=max_sftp_list_entries,
    )


class PayloadTooLargeError(ValueError):
    pass


def _truncate_text(text: str, max_bytes: int) -> tuple[str, bool]:
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text, False
    truncated = data[:max_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8"), True
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return "", True
