import json
import unittest
from unittest.mock import Mock

from jumpserver_mcp_server.tools import (
    CommandPolicy,
    CommandResult,
    PayloadTooLargeError,
    ToolErrorCode,
    build_tool_result,
    create_tools,
)


class FakePool:
    def __init__(self):
        self.commands = []
        self.uploads = []
        self.downloads = []
        self.lists = []

    def run_command(self, asset_ip, system_user, command, timeout=None):
        self.commands.append((asset_ip, system_user, command, timeout))
        return CommandResult(stdout="hello\n", stderr="")

    def upload(self, asset_ip, system_user, remote_path, data):
        self.uploads.append((asset_ip, system_user, remote_path, data))

    def download(self, asset_ip, system_user, remote_path, max_bytes=None):
        self.downloads.append((asset_ip, system_user, remote_path, max_bytes))
        return b"hello\n"

    def list_dir(self, asset_ip, system_user, remote_path, limit=None):
        self.lists.append((asset_ip, system_user, remote_path))
        attr = Mock()
        attr.filename = "hello.txt"
        attr.st_size = 6
        attr.st_mode = 0o100644
        return [attr]


class ToolResponseTests(unittest.TestCase):
    def test_build_tool_result_uses_structured_json_shape(self):
        result = json.loads(build_tool_result(True, "OK", data={"value": 1}))

        self.assertEqual(
            result,
            {
                "success": True,
                "error": None,
                "code": "OK",
                "message": "OK",
                "data": {"value": 1},
            },
        )

    def test_ssh_command_returns_structured_json_and_uses_configured_timeout(self):
        pool = FakePool()
        tools = create_tools(pool, default_system_user="root", command_timeout=12)

        text = tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "whoami"})
        result = json.loads(text)

        self.assertTrue(result["success"])
        self.assertEqual(result["code"], "OK")
        self.assertEqual(
            result["data"],
            {
                "stdout": "hello\n",
                "stderr": "",
                "output": "STDOUT:\nhello\n",
                "exit_status": None,
                "truncated": False,
            },
        )
        self.assertEqual(pool.commands, [("10.0.0.1", "root", "whoami", 12)])

    def test_ssh_command_truncates_large_output(self):
        pool = FakePool()
        pool.run_command = lambda asset_ip, system_user, command, timeout=None: CommandResult(
            stdout="abcdef", stderr=""
        )
        tools = create_tools(pool, default_system_user="root", command_timeout=30, max_command_output_bytes=3)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "cat big"})
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["stdout"], "abc")
        self.assertTrue(result["data"]["truncated"])

    def test_ssh_command_truncates_utf8_on_character_boundary(self):
        pool = FakePool()
        pool.run_command = lambda asset_ip, system_user, command, timeout=None: CommandResult(
            stdout="你abc", stderr=""
        )
        tools = create_tools(pool, default_system_user="root", command_timeout=30, max_command_output_bytes=4)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "cat big"})
        )

        self.assertEqual(result["data"]["stdout"], "你a")
        self.assertTrue(result["data"]["truncated"])

    def test_ssh_command_truncates_utf8_without_partial_character(self):
        pool = FakePool()
        pool.run_command = lambda asset_ip, system_user, command, timeout=None: CommandResult(
            stdout="你a", stderr=""
        )
        tools = create_tools(pool, default_system_user="root", command_timeout=30, max_command_output_bytes=2)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "cat big"})
        )

        self.assertEqual(result["data"]["stdout"], "")
        self.assertTrue(result["data"]["truncated"])

    def test_missing_required_argument_returns_structured_error(self):
        tools = create_tools(FakePool(), default_system_user="root", command_timeout=30)

        result = json.loads(tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1"}))

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.INVALID_ARGUMENT.value)
        self.assertEqual(result["data"], {})
        self.assertIn("command", result["message"])

    def test_asset_ip_rejects_ssh_username_separators(self):
        tools = create_tools(FakePool(), default_system_user="root", command_timeout=30)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1@other", "command": "whoami"})
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.INVALID_ARGUMENT.value)
        self.assertIn("asset_ip", result["message"])

    def test_system_user_rejects_ssh_username_separators(self):
        tools = create_tools(FakePool(), default_system_user="root", command_timeout=30)

        result = json.loads(
            tools.call(
                "jumpserver_ssh_command",
                {"asset_ip": "10.0.0.1", "system_user": "root@other", "command": "whoami"},
            )
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.INVALID_ARGUMENT.value)
        self.assertIn("system_user", result["message"])

    def test_command_blacklist_blocks_dangerous_command_before_pool_call(self):
        pool = FakePool()
        policy = CommandPolicy(mode="blacklist", patterns=["rm -rf /"])
        tools = create_tools(pool, default_system_user="root", command_timeout=30, command_policy=policy)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "rm -rf /"})
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.COMMAND_BLOCKED.value)
        self.assertEqual(pool.commands, [])

    def test_command_whitelist_allows_only_matching_command(self):
        pool = FakePool()
        policy = CommandPolicy(mode="whitelist", patterns=["df *", "whoami"])
        tools = create_tools(pool, default_system_user="root", command_timeout=30, command_policy=policy)

        blocked = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "uptime"})
        )
        allowed = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "df -h"})
        )

        self.assertFalse(blocked["success"])
        self.assertEqual(blocked["code"], ToolErrorCode.COMMAND_BLOCKED.value)
        self.assertTrue(allowed["success"])
        self.assertEqual(pool.commands, [("10.0.0.1", "root", "df -h", 30)])

    def test_command_whitelist_rejects_shell_control_operators(self):
        pool = FakePool()
        policy = CommandPolicy(mode="whitelist", patterns=["df *"])
        tools = create_tools(pool, default_system_user="root", command_timeout=30, command_policy=policy)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "df -h; rm -rf /"})
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.COMMAND_BLOCKED.value)
        self.assertEqual(pool.commands, [])

    def test_command_whitelist_rejects_subshell_expansion(self):
        pool = FakePool()
        policy = CommandPolicy(mode="whitelist", patterns=["echo *"])
        tools = create_tools(pool, default_system_user="root", command_timeout=30, command_policy=policy)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "echo $(whoami)"})
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.COMMAND_BLOCKED.value)
        self.assertEqual(pool.commands, [])

    def test_command_whitelist_still_allows_safe_matching_arguments(self):
        pool = FakePool()
        policy = CommandPolicy(mode="whitelist", patterns=["df *"])
        tools = create_tools(pool, default_system_user="root", command_timeout=30, command_policy=policy)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "df -h"})
        )

        self.assertTrue(result["success"])
        self.assertEqual(pool.commands, [("10.0.0.1", "root", "df -h", 30)])

    def test_command_whitelist_without_patterns_blocks_all_commands(self):
        pool = FakePool()
        policy = CommandPolicy(mode="whitelist", patterns=[])
        tools = create_tools(pool, default_system_user="root", command_timeout=30, command_policy=policy)

        result = json.loads(
            tools.call("jumpserver_ssh_command", {"asset_ip": "10.0.0.1", "command": "whoami"})
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.COMMAND_BLOCKED.value)
        self.assertEqual(pool.commands, [])

    def test_invalid_command_policy_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            CommandPolicy(mode="blackist", patterns=["rm *"])

    def test_sftp_upload_decodes_base64_and_returns_json(self):
        pool = FakePool()
        tools = create_tools(pool, default_system_user="root", command_timeout=30)

        result = json.loads(
            tools.call(
                "jumpserver_sftp_upload",
                {"asset_ip": "10.0.0.1", "remote_path": "hello.bin", "content_base64": "aGk="},
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"remote_path": "hello.bin", "bytes": 2})
        self.assertEqual(pool.uploads, [("10.0.0.1", "root", "hello.bin", b"hi")])

    def test_sftp_download_returns_text_or_base64_json(self):
        pool = FakePool()
        tools = create_tools(pool, default_system_user="root", command_timeout=30)

        result = json.loads(
            tools.call("jumpserver_sftp_download", {"asset_ip": "10.0.0.1", "remote_path": "hello.txt"})
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"], {"remote_path": "hello.txt", "encoding": "text", "content": "hello\n"})

    def test_sftp_list_returns_structured_entries(self):
        pool = FakePool()
        tools = create_tools(pool, default_system_user="root", command_timeout=30)

        result = json.loads(tools.call("jumpserver_sftp_list", {"asset_ip": "10.0.0.1"}))

        self.assertTrue(result["success"])
        self.assertEqual(
            result["data"],
            {"remote_path": ".", "entries": [{"name": "hello.txt", "size": 6, "type": "file"}], "truncated": False},
        )
    def test_sftp_upload_rejects_content_over_limit(self):
        pool = FakePool()
        tools = create_tools(pool, default_system_user="root", command_timeout=30, max_sftp_upload_bytes=2)

        result = json.loads(
            tools.call("jumpserver_sftp_upload", {"asset_ip": "10.0.0.1", "remote_path": "big.txt", "content": "abc"})
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.PAYLOAD_TOO_LARGE.value)
        self.assertEqual(pool.uploads, [])

    def test_sftp_download_rejects_file_over_limit(self):
        class BigDownloadPool(FakePool):
            def download(self, asset_ip, system_user, remote_path, max_bytes=None):
                self.downloads.append((asset_ip, system_user, remote_path, max_bytes))
                raise PayloadTooLargeError("download exceeds max_sftp_download_bytes")

        pool = BigDownloadPool()
        tools = create_tools(pool, default_system_user="root", command_timeout=30, max_sftp_download_bytes=2)

        result = json.loads(
            tools.call("jumpserver_sftp_download", {"asset_ip": "10.0.0.1", "remote_path": "big.txt"})
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["code"], ToolErrorCode.PAYLOAD_TOO_LARGE.value)
        self.assertEqual(pool.downloads, [("10.0.0.1", "root", "big.txt", 2)])

    def test_sftp_list_caps_entries(self):
        pool = FakePool()
        for index in range(3):
            attr = Mock()
            attr.filename = f"file{index}.txt"
            attr.st_size = index
            attr.st_mode = 0o100644
            pool.lists.append(attr)
        pool.list_dir = lambda asset_ip, system_user, remote_path, limit=None: pool.lists[:limit]
        tools = create_tools(pool, default_system_user="root", command_timeout=30, max_sftp_list_entries=2)

        result = json.loads(tools.call("jumpserver_sftp_list", {"asset_ip": "10.0.0.1"}))

        self.assertTrue(result["success"])
        self.assertEqual(len(result["data"]["entries"]), 2)
        self.assertTrue(result["data"]["truncated"])


if __name__ == "__main__":
    unittest.main()
