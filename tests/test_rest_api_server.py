import unittest

from jumpserver_mcp_server.rest_api import BearerAuth, JumpserverAccessKeyAuth, build_api_auth, derive_api_base_url, derive_swagger_url


class RestApiServerTests(unittest.TestCase):
    def test_derives_swagger_url_from_jumpserver_url(self):
        self.assertEqual(
            derive_swagger_url("", "http://jumpserver.ks.gillion.com.cn"),
            "http://jumpserver.ks.gillion.com.cn/api/swagger.json",
        )

    def test_derives_api_base_url_from_jumpserver_url(self):
        self.assertEqual(
            derive_api_base_url("", "http://jumpserver.ks.gillion.com.cn"),
            "http://jumpserver.ks.gillion.com.cn/api/v1",
        )

    def test_prefers_access_key_auth_over_bearer_token(self):
        auth = build_api_auth(api_token="token", access_key_id="id", access_key_secret="secret")

        self.assertIsInstance(auth, JumpserverAccessKeyAuth)

    def test_uses_bearer_auth_when_token_configured_without_access_key(self):
        auth = build_api_auth(api_token="token", access_key_id="", access_key_secret="")

        self.assertIsInstance(auth, BearerAuth)

    def test_returns_no_auth_when_credentials_missing(self):
        self.assertIsNone(build_api_auth(api_token="", access_key_id="", access_key_secret=""))


if __name__ == "__main__":
    unittest.main()
