import time
import unittest
from unittest.mock import Mock, patch

import paramiko

from jumpserver_mcp_server.connection_pool import SSHConnectionPool


class FakeChannel:
    def __init__(self, exit_status=0):
        self._exit_status = exit_status

    def recv_exit_status(self):
        return self._exit_status


class FakeStream:
    def __init__(self, text="", exit_status=0):
        self._text = text
        self.channel = FakeChannel(exit_status)

    def read(self):
        return self._text.encode("utf-8")


class FakeSFTP:
    def __init__(self):
        self.closed = False
        self.uploaded = []
        self.download_data = b"data"
        self.attrs = []

    def putfo(self, file_obj, remote_path):
        self.uploaded.append((remote_path, file_obj.read()))

    def getfo(self, remote_path, file_obj):
        file_obj.write(self.download_data)

    def listdir_attr(self, remote_path):
        return self.attrs

    def stat(self, remote_path):
        return object()

    def close(self):
        self.closed = True


class FakeSSHClient:
    instances = []

    def __init__(self):
        self.connected = False
        self.closed = False
        self.connect_kwargs = None
        self.commands = []
        self.loaded_system_host_keys = False
        self.loaded_host_keys = None
        self.sftp = FakeSFTP()
        FakeSSHClient.instances.append(self)

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def load_system_host_keys(self):
        self.loaded_system_host_keys = True

    def load_host_keys(self, filename):
        self.loaded_host_keys = filename

    def connect(self, **kwargs):
        self.connected = True
        self.connect_kwargs = kwargs

    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        if command == "echo mcp_health_check":
            return None, FakeStream("mcp_health_check\n"), FakeStream("")
        return None, FakeStream("ok\n"), FakeStream("")

    def open_sftp(self):
        return self.sftp

    def close(self):
        self.closed = True


class BrokenHealthSSHClient(FakeSSHClient):
    def exec_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        if command == "echo mcp_health_check":
            raise OSError("dead")
        return None, FakeStream("ok\n"), FakeStream("")


class SSHConnectionPoolTests(unittest.TestCase):
    def setUp(self):
        FakeSSHClient.instances = []

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", FakeSSHClient)
    def test_reuses_connection_for_same_asset_and_user(self):
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            connect_timeout=5,
            max_connections=4,
            idle_timeout=60,
        )

        first = pool.run_command("10.0.0.1", "root", "whoami", timeout=7)
        second = pool.run_command("10.0.0.1", "root", "hostname", timeout=7)

        self.assertEqual(first.stdout, "ok\n")
        self.assertEqual(first.stderr, "")
        self.assertEqual(first.exit_status, 0)
        self.assertEqual(first.output, "STDOUT:\nok\n")
        self.assertEqual(second.stdout, "ok\n")
        self.assertEqual(len(FakeSSHClient.instances), 1)
        self.assertEqual(
            FakeSSHClient.instances[0].connect_kwargs["username"], "gateway@root@10.0.0.1"
        )
        self.assertEqual(FakeSSHClient.instances[0].commands[-1], ("hostname", 7))

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", FakeSSHClient)
    def test_rejects_unknown_host_keys_by_default(self):
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            connect_timeout=5,
            max_connections=4,
            idle_timeout=60,
        )

        pool.run_command("10.0.0.1", "root", "whoami")

        client = FakeSSHClient.instances[0]
        self.assertIsInstance(client.policy, paramiko.RejectPolicy)
        self.assertTrue(client.loaded_system_host_keys)

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", FakeSSHClient)
    def test_loads_configured_known_hosts_file(self):
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            gateway_known_hosts_path="/tmp/known_hosts",
            connect_timeout=5,
            max_connections=4,
            idle_timeout=60,
        )

        pool.run_command("10.0.0.1", "root", "whoami")

        self.assertEqual(FakeSSHClient.instances[0].loaded_host_keys, "/tmp/known_hosts")

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", FakeSSHClient)
    def test_uses_key_filename_when_configured(self):
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            gateway_private_key_path="/tmp/id_rsa",
            connect_timeout=5,
            max_connections=4,
            idle_timeout=60,
        )

        pool.run_command("10.0.0.1", "root", "whoami")

        kwargs = FakeSSHClient.instances[0].connect_kwargs
        self.assertEqual(kwargs["key_filename"], "/tmp/id_rsa")
        self.assertIsNone(kwargs["password"])
        self.assertFalse(kwargs["look_for_keys"])
        self.assertFalse(kwargs["allow_agent"])

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", BrokenHealthSSHClient)
    def test_rebuilds_connection_when_health_check_fails(self):
        now = [100.0]
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            connect_timeout=5,
            max_connections=4,
            idle_timeout=60,
            health_check_interval=0,
            now=lambda: now[0],
        )

        pool.run_command("10.0.0.1", "root", "first")
        now[0] = 101.0
        pool.run_command("10.0.0.1", "root", "second")

        self.assertEqual(len(FakeSSHClient.instances), 2)
        self.assertTrue(FakeSSHClient.instances[0].closed)

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", FakeSSHClient)
    def test_evicts_least_recently_used_connection_when_pool_is_full(self):
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            connect_timeout=5,
            max_connections=1,
            idle_timeout=60,
        )

        pool.run_command("10.0.0.1", "root", "one")
        first = FakeSSHClient.instances[0]
        pool.run_command("10.0.0.2", "root", "two")

        self.assertTrue(first.closed)
        self.assertEqual(len(FakeSSHClient.instances), 2)

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", FakeSSHClient)
    def test_closes_idle_connections_before_reuse(self):
        now = [100.0]
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            connect_timeout=5,
            max_connections=4,
            idle_timeout=10,
            now=lambda: now[0],
        )

        pool.run_command("10.0.0.1", "root", "one")
        first = FakeSSHClient.instances[0]
        now[0] = 111.0
        pool.run_command("10.0.0.1", "root", "two")

        self.assertTrue(first.closed)
        self.assertEqual(len(FakeSSHClient.instances), 2)

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", FakeSSHClient)
    def test_skips_repeated_health_check_until_interval_expires(self):
        now = [100.0]
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            connect_timeout=5,
            max_connections=4,
            idle_timeout=60,
            health_check_interval=30,
            now=lambda: now[0],
        )

        pool.run_command("10.0.0.1", "root", "one")
        pool.run_command("10.0.0.1", "root", "two")
        now[0] = 131.0
        pool.run_command("10.0.0.1", "root", "three")

        client = FakeSSHClient.instances[0]
        self.assertEqual(
            client.commands,
            [
                ("one", None),
                ("two", None),
                ("echo mcp_health_check", 5),
                ("three", None),
            ],
        )

    @patch("jumpserver_mcp_server.connection_pool.paramiko.SSHClient", FakeSSHClient)
    def test_sftp_operations_use_pooled_connection_and_close_sftp_only(self):
        pool = SSHConnectionPool(
            gateway_host="jms.example",
            gateway_port=2222,
            gateway_username="gateway",
            gateway_password="secret",
            connect_timeout=5,
            max_connections=4,
            idle_timeout=60,
        )

        pool.upload("10.0.0.1", "root", "hello.txt", b"hello")
        data = pool.download("10.0.0.1", "root", "hello.txt")
        pool.list_dir("10.0.0.1", "root", ".")

        client = FakeSSHClient.instances[0]
        self.assertEqual(len(FakeSSHClient.instances), 1)
        self.assertFalse(client.closed)
        self.assertEqual(client.sftp.uploaded, [("hello.txt", b"hello")])
        self.assertEqual(data, b"data")


if __name__ == "__main__":
    unittest.main()
