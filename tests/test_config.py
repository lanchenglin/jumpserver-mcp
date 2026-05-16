import unittest

from jumpserver_mcp_server.config import Settings


class SettingsTests(unittest.TestCase):
    def test_default_pool_idle_timeout_stays_below_jumpserver_idle_disconnect(self):
        settings = Settings(_env_file=None)

        self.assertEqual(settings.ssh_pool_idle_timeout, 1500)


if __name__ == "__main__":
    unittest.main()
