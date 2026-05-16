import unittest
from concurrent.futures import ThreadPoolExecutor

from jumpserver_mcp_server import server


class ServerExecutorTests(unittest.TestCase):
    def test_uses_bounded_executor_for_blocking_tool_calls(self):
        self.assertIsInstance(server.tool_executor, ThreadPoolExecutor)
        self.assertEqual(server.tool_executor._max_workers, server.settings.mcp_worker_threads)


if __name__ == "__main__":
    unittest.main()
