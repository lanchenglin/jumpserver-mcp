# JumpServer MCP Server

JumpServer MCP Server exposes JumpServer REST API tools generated from the JumpServer OpenAPI `swagger.json` schema.

This version is focused on JumpServer API operations such as asset and user management. It does not expose SSH or SFTP tools.

## Configure JumpServer Environment File (.env)

```txt
# Optional: protect MCP HTTP endpoint with an API key
api_key=your-mcp-http-api-key

# JumpServer REST API endpoint
jumpserver_url=http://jumpserver.ks.gillion.com.cn
# Optional overrides. If empty, they are derived from jumpserver_url.
api_base_url=
swagger_url=

# JumpServer API authentication.
# Access Key is preferred when both Access Key and Bearer token are configured.
access_key_id=your-access-key-id
access_key_secret=your-access-key-secret
# api_token=your-bearer-token

# Organization ID is kept for compatibility and sent as X-JMS-ORG when configured.
jms_org_id=00000000-0000-0000-0000-000000000002
```

Copy `.env.example` to `.env` and fill in your values. Do not commit `.env`.

## Start Docker Container

```bash
docker run -d -it -p 8099:8099 --env-file .env --name jms_mcp ghcr.io/jumpserver/mcp:latest
```

## MCP Server Configuration

```json
{
  "type": "sse",
  "url": "http://127.0.0.1:8099/sse",
  "headers": {
    "Authorization": "Bearer xxxxxxxx"
  }
}
```

If `api_key` is empty, omit `headers`.

## REST API Tool Generation

At startup, the server fetches the JumpServer OpenAPI schema from:

```txt
http://jumpserver.ks.gillion.com.cn/api/swagger.json
```

If `swagger_url` is configured, that value is used instead. The API base URL defaults to:

```txt
http://jumpserver.ks.gillion.com.cn/api/v1
```

If `api_base_url` is configured, that value is used instead.

The MCP tool list is generated dynamically from the JumpServer OpenAPI schema. Each API operation becomes an MCP tool that proxies requests to JumpServer.

If the remote swagger fetch fails (e.g., token expired), the server falls back to a cached copy, then to a bundled fallback schema covering core APIs. When authentication is restored, a fresh schema is fetched and cached automatically.

## Authentication

The server supports two JumpServer API authentication modes:

1. Access Key: `access_key_id` + `access_key_secret`
2. Bearer token: `api_token`

Access Key takes precedence when both are configured.

## Security Notes

Protect the MCP endpoint with `api_key` if it is reachable outside localhost. JumpServer API permissions should be scoped to the minimum required operations for the AI client.
