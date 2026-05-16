from __future__ import annotations

import io
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator

import paramiko

from .tools import CommandResult, PayloadTooLargeError


@dataclass
class PooledConnection:
    client: paramiko.SSHClient
    last_used: float
    last_health_check: float
    in_use: int = 0
    close_when_released: bool = False


class SSHConnectionPool:
    def __init__(
        self,
        *,
        gateway_host: str,
        gateway_port: int,
        gateway_username: str,
        gateway_password: str = "",
        gateway_private_key_path: str = "",
        gateway_known_hosts_path: str = "",
        connect_timeout: int = 30,
        max_connections: int = 10,
        idle_timeout: int = 300,
        health_check_interval: int = 60,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.gateway_username = gateway_username
        self.gateway_password = gateway_password
        self.gateway_private_key_path = gateway_private_key_path
        self.gateway_known_hosts_path = gateway_known_hosts_path
        self.connect_timeout = connect_timeout
        self.max_connections = max_connections
        self.idle_timeout = idle_timeout
        self.health_check_interval = health_check_interval
        self._now = now or time.monotonic
        self._connections: dict[tuple[str, str], PooledConnection] = {}
        self._locks: dict[tuple[str, str], threading.Lock] = {}
        self._lock = threading.RLock()

    def run_command(
        self, asset_ip: str, system_user: str, command: str, timeout: int | None = None
    ) -> CommandResult:
        with self._client(asset_ip, system_user) as client:
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            out = stdout.read().decode(errors="ignore")
            err = stderr.read().decode(errors="ignore")
            exit_status = getattr(getattr(stdout, "channel", None), "recv_exit_status", lambda: None)()
            return CommandResult(stdout=out, stderr=err, exit_status=exit_status)

    def upload(self, asset_ip: str, system_user: str, remote_path: str, data: bytes) -> None:
        with self._client(asset_ip, system_user) as client:
            sftp = client.open_sftp()
            try:
                self._makedirs(sftp, os.path.dirname(remote_path))
                sftp.putfo(io.BytesIO(data), remote_path)
            finally:
                sftp.close()

    def download(
        self, asset_ip: str, system_user: str, remote_path: str, max_bytes: int | None = None
    ) -> bytes:
        with self._client(asset_ip, system_user) as client:
            sftp = client.open_sftp()
            try:
                buf = LimitedBytesIO(max_bytes)
                sftp.getfo(remote_path, buf)
                return buf.getvalue()
            finally:
                sftp.close()

    def list_dir(
        self, asset_ip: str, system_user: str, remote_path: str, limit: int | None = None
    ):
        with self._client(asset_ip, system_user) as client:
            sftp = client.open_sftp()
            try:
                attrs = sftp.listdir_attr(remote_path)
                return attrs if limit is None else attrs[:limit]
            finally:
                sftp.close()

    def close_all(self) -> None:
        with self._lock:
            connections = list(self._connections.values())
            self._connections.clear()
            self._locks.clear()
        for connection in connections:
            connection.client.close()

    @contextmanager
    def _client(self, asset_ip: str, system_user: str) -> Iterator[paramiko.SSHClient]:
        key = (asset_ip, system_user)
        connection = self._acquire_connection(key, asset_ip, system_user)
        try:
            yield connection.client
        finally:
            self._release_connection(key, connection)

    def _acquire_connection(
        self, key: tuple[str, str], asset_ip: str, system_user: str
    ) -> PooledConnection:
        key_lock = self._key_lock(key)
        close_after_acquire: list[PooledConnection] = []
        with key_lock:
            connection, idle_connections = self._take_existing_connection(key)
            close_after_acquire.extend(idle_connections)
            if connection is not None:
                if self._connection_is_reusable(connection):
                    with self._lock:
                        connection.in_use += 1
                        connection.last_used = self._now()
                        self._connections[key] = connection
                    self._close_connections(close_after_acquire)
                    return connection
                connection.client.close()

            client = self._connect(asset_ip, system_user)
            connection = PooledConnection(
                client=client,
                last_used=self._now(),
                last_health_check=self._now(),
                in_use=1,
            )
            with self._lock:
                existing = self._connections.pop(key, None)
                idle_connections = self._pop_idle_locked()
                evicted = self._pop_lru_if_needed_locked()
                self._connections[key] = connection
            close_after_acquire.extend(item for item in [existing, evicted] if item is not None)
            close_after_acquire.extend(idle_connections)
        self._close_connections(close_after_acquire)
        return connection

    def _key_lock(self, key: tuple[str, str]) -> threading.Lock:
        with self._lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _release_connection(self, key: tuple[str, str], connection: PooledConnection) -> None:
        should_close = False
        with self._lock:
            connection.in_use -= 1
            connection.last_used = self._now()
            if connection.close_when_released and connection.in_use == 0:
                self._connections.pop(key, None)
                should_close = True
        if should_close:
            connection.client.close()

    def _take_existing_connection(
        self, key: tuple[str, str]
    ) -> tuple[PooledConnection | None, list[PooledConnection]]:
        with self._lock:
            idle_connections = self._pop_idle_locked()
            return self._connections.pop(key, None), idle_connections

    def _connection_is_reusable(self, connection: PooledConnection) -> bool:
        now = self._now()
        if now - connection.last_health_check <= self.health_check_interval:
            return True
        if not self._is_healthy(connection.client):
            return False
        connection.last_health_check = now
        return True

    def _connect(self, asset_ip: str, system_user: str) -> paramiko.SSHClient:
        if not self.gateway_host or not self.gateway_username:
            raise ConnectionError("SSH 网关未配置（ssh_gateway_host / ssh_gateway_username 为空）")

        client = paramiko.SSHClient()
        if self.gateway_known_hosts_path:
            client.load_host_keys(self.gateway_known_hosts_path)
        else:
            client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        kwargs = {
            "hostname": self.gateway_host,
            "port": self.gateway_port,
            "username": f"{self.gateway_username}@{system_user}@{asset_ip}",
            "password": self.gateway_password or None,
            "look_for_keys": False,
            "allow_agent": False,
            "timeout": self.connect_timeout,
        }
        if self.gateway_private_key_path:
            kwargs["key_filename"] = self.gateway_private_key_path
            kwargs["password"] = None
        client.connect(**kwargs)
        return client

    def _is_healthy(self, client: paramiko.SSHClient) -> bool:
        try:
            _, stdout, _ = client.exec_command("echo mcp_health_check", timeout=5)
            return stdout.read().decode(errors="ignore").strip() == "mcp_health_check"
        except Exception:
            return False

    def _pop_idle_locked(self) -> list[PooledConnection]:
        now = self._now()
        idle_keys = [
            key
            for key, connection in self._connections.items()
            if connection.in_use == 0 and now - connection.last_used > self.idle_timeout
        ]
        idle_connections = []
        for key in idle_keys:
            idle_connections.append(self._connections.pop(key))
        return idle_connections

    def _pop_lru_if_needed_locked(self) -> PooledConnection | None:
        if len(self._connections) < self.max_connections:
            return None
        candidates = [
            (key, connection)
            for key, connection in self._connections.items()
            if connection.in_use == 0
        ]
        if candidates:
            key, connection = min(candidates, key=lambda item: item[1].last_used)
            del self._connections[key]
            return connection
        key, connection = min(self._connections.items(), key=lambda item: item[1].last_used)
        connection.close_when_released = True
        return None

    def _close_connections(self, connections: list[PooledConnection]) -> None:
        for connection in connections:
            connection.client.close()

    def _makedirs(self, sftp: paramiko.SFTPClient, dir_path: str) -> None:
        if not dir_path or dir_path == "." or dir_path == "/":
            return
        path = dir_path.rstrip("/")
        parts = [part for part in path.split("/") if part]
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else f"/{part}"
            try:
                sftp.stat(current)
            except OSError:
                sftp.mkdir(current)


class LimitedBytesIO(io.BytesIO):
    def __init__(self, max_bytes: int | None) -> None:
        super().__init__()
        self.max_bytes = max_bytes

    def write(self, data: bytes) -> int:
        if self.max_bytes is not None and self.tell() + len(data) > self.max_bytes:
            raise PayloadTooLargeError("download exceeds max_sftp_download_bytes")
        return super().write(data)
