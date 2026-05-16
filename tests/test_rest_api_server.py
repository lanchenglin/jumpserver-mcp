import json
import unittest
from unittest.mock import MagicMock, patch

from jumpserver_mcp_server.rest_api import (
    BearerAuth,
    JumpserverAccessKeyAuth,
    build_api_auth,
    derive_api_base_url,
    derive_swagger_url,
    get_swagger_json,
)


class RestApiServerTests(unittest.TestCase):
    def test_derives_swagger_url_from_jumpserver_url(self):
        self.assertEqual(
            derive_swagger_url("", "http://jumpserver.ks.gillion.com.cn"),
            "http://jumpserver.ks.gillion.com.cn/api/swagger.json",
        )

    def test_uses_explicit_swagger_url(self):
        self.assertEqual(
            derive_swagger_url("http://other/swagger.json", "http://jumpserver"),
            "http://other/swagger.json",
        )

    def test_derives_api_base_url_from_jumpserver_url(self):
        self.assertEqual(
            derive_api_base_url("", "http://jumpserver.ks.gillion.com.cn"),
            "http://jumpserver.ks.gillion.com.cn/api/v1",
        )

    def test_uses_explicit_api_base_url(self):
        self.assertEqual(
            derive_api_base_url("http://custom/api", "http://jumpserver"),
            "http://custom/api",
        )

    def test_prefers_access_key_auth_over_bearer_token(self):
        auth = build_api_auth(api_token="token", access_key_id="id", access_key_secret="secret")
        self.assertIsInstance(auth, JumpserverAccessKeyAuth)

    def test_uses_bearer_auth_when_token_configured_without_access_key(self):
        auth = build_api_auth(api_token="token", access_key_id="", access_key_secret="")
        self.assertIsInstance(auth, BearerAuth)

    def test_returns_no_auth_when_credentials_missing(self):
        self.assertIsNone(build_api_auth(api_token="", access_key_id="", access_key_secret=""))


class SwaggerFetchTests(unittest.TestCase):
    @patch("jumpserver_mcp_server.rest_api.httpx.get")
    @patch("jumpserver_mcp_server.rest_api.settings")
    def test_fetches_and_caches_swagger(self, mock_settings, mock_get):
        mock_settings.api_token = "test-token"
        mock_settings.access_key_id = ""
        mock_settings.access_key_secret = ""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"openapi": "3.0", "paths": {}}
        mock_get.return_value = mock_response

        with patch("jumpserver_mcp_server.rest_api._save_swagger_cache") as mock_save:
            result = get_swagger_json("http://test/swagger.json")
            self.assertEqual(result, {"openapi": "3.0", "paths": {}})
            mock_save.assert_called_once()

    @patch("jumpserver_mcp_server.rest_api.httpx.get")
    @patch("jumpserver_mcp_server.rest_api.settings")
    def test_falls_back_to_cache_on_failure(self, mock_settings, mock_get):
        mock_settings.api_token = ""
        mock_settings.access_key_id = ""
        mock_settings.access_key_secret = ""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_get.return_value = mock_response

        cached_data = {"openapi": "3.0", "paths": {"/test": {}}}
        with patch("jumpserver_mcp_server.rest_api._load_swagger_cache", return_value=cached_data):
            result = get_swagger_json("http://test/swagger.json")
            self.assertEqual(result, cached_data)

    @patch("jumpserver_mcp_server.rest_api.httpx.get")
    @patch("jumpserver_mcp_server.rest_api.settings")
    def test_falls_back_to_bundled_on_no_cache(self, mock_settings, mock_get):
        mock_settings.api_token = ""
        mock_settings.access_key_id = ""
        mock_settings.access_key_secret = ""
        mock_get.side_effect = Exception("connection error")

        with patch("jumpserver_mcp_server.rest_api._load_swagger_cache", return_value=None):
            result = get_swagger_json("http://test/swagger.json")
            self.assertIn("paths", result)
            self.assertIn("/assets/assets/", result["paths"])


class ToolParsingTests(unittest.TestCase):
    def _make_swagger(self):
        with open("jumpserver_mcp_server/fallback_swagger.json") as f:
            return json.load(f)

    def test_parse_swagger_registers_tools(self):
        from jumpserver_mcp_server.server import parse_swagger_to_tools
        from mcp.server.fastmcp import FastMCP
        import httpx

        mcp = FastMCP(name="test")
        client = httpx.AsyncClient()
        swagger = self._make_swagger()
        parse_swagger_to_tools(swagger, mcp, client, "http://test/api/v1")
        # Check that tool functions were registered by listing them
        tools = mcp._tool_manager.list_tools()
        self.assertGreater(len(tools), 0)
        tool_names = [t.name for t in tools]
        self.assertIn("assets_assets_list", tool_names)
        self.assertIn("users_users_create", tool_names)


if __name__ == "__main__":
    unittest.main()
