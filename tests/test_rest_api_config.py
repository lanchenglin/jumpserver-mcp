import unittest

from jumpserver_mcp_server.config import Settings


class RestApiConfigTests(unittest.TestCase):
    def test_defaults_to_requested_jumpserver_url(self):
        settings = Settings(_env_file=None)
        self.assertEqual(settings.jumpserver_url, "http://jumpserver.ks.gillion.com.cn")

    def test_removes_ssh_specific_settings(self):
        settings = Settings(_env_file=None)
        self.assertFalse(hasattr(settings, "ssh_gateway_host"))
        self.assertFalse(hasattr(settings, "ssh_gateway_password"))
        self.assertFalse(hasattr(settings, "ssh_pool_idle_timeout"))

    def test_default_port(self):
        settings = Settings(_env_file=None)
        self.assertEqual(settings.server_port, 8099)


if __name__ == "__main__":
    unittest.main()
