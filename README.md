# JumpServer MCP Server

JumpServer MCP Server exposes four SSH/SFTP tools for AI clients to operate assets through the JumpServer SSH gateway.

This optimized version no longer fetches `swagger.json` at startup and no longer generates JumpServer OpenAPI tools. The MCP tool list is intentionally limited to SSH/SFTP operations.

## Configure JumpServer Environment File (.env)

```txt
# Optional: Protect MCP HTTP endpoint with an API key
api_key=your-mcp-http-api-key

# JumpServer SSH gateway
ssh_gateway_host=your-ssh-gateway-host
ssh_gateway_port=2222
ssh_gateway_username=your-gateway-username
ssh_gateway_password=your-gateway-password
# Optional: use SSH private key authentication instead of password
ssh_gateway_private_key_path=
# Optional: known_hosts file for gateway host key verification
ssh_gateway_known_hosts_path=
default_system_user=root

# SSH/SFTP connection pool and timeout settings
ssh_connect_timeout=30
ssh_command_timeout=30
ssh_pool_max_connections=10
ssh_pool_idle_timeout=1500
ssh_health_check_interval=60

# Optional command policy: none / blacklist / whitelist
# Patterns are comma-separated and support shell wildcards.
ssh_command_policy_mode=none
ssh_command_policy_patterns=

# Resource limits
mcp_worker_threads=8
max_command_output_bytes=1048576
max_sftp_upload_bytes=10485760
max_sftp_download_bytes=10485760
max_sftp_list_entries=1000
```

Existing JumpServer HTTP API variables such as `jumpserver_url`, `api_token`, `access_key_id`, `access_key_secret`, and `jms_org_id` are still accepted for `.env` compatibility, but SSH/SFTP tools do not use them.

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

## Tools

The server exposes exactly four MCP tools:

- `jumpserver_ssh_command` — execute a shell command on an asset.
- `jumpserver_sftp_upload` — upload text or Base64 content to a remote file path.
- `jumpserver_sftp_download` — download file content from a remote path.
- `jumpserver_sftp_list` — list directory contents on an asset.

### jumpserver_ssh_command

Input schema:

- `asset_ip` (string, required): target asset IP, for example `192.168.1.100`.
- `system_user` (string, optional): system username on the target asset. Defaults to `default_system_user`.
- `command` (string, required): shell command to execute, for example `df -h`.

The command execution timeout uses `ssh_command_timeout`. SSH connection setup uses `ssh_connect_timeout`. Output is capped by `max_command_output_bytes`; when capped, response data includes `truncated: true`.

### Structured result format

All tools return MCP text content containing JSON:

```json
{
  "success": true,
  "error": null,
  "code": "OK",
  "message": "OK",
  "data": {}
}
```

Errors use the same shape with `success: false`, a non-`OK` `code`, and a human-readable `message`. Oversized command output, uploads, or downloads return `PAYLOAD_TOO_LARGE` or a truncated successful command result as appropriate.

## Connection Pool

SSH connections are pooled by `asset_ip + system_user`. Reused connections are health-checked with a lightweight `echo mcp_health_check` command; disconnected or timed-out sessions are rebuilt automatically.

Pool controls:

- `ssh_pool_max_connections`: maximum pooled SSH connections.
- `ssh_pool_idle_timeout`: seconds before idle connections are closed. Default `1500` keeps pooled sessions below JumpServer's 30-minute idle disconnect.
- `ssh_health_check_interval`: minimum seconds between command-based health checks for a reused connection.

Resource controls:

- `mcp_worker_threads`: maximum concurrent blocking SSH/SFTP tool calls.
- `max_command_output_bytes`: maximum stdout/stderr bytes returned per SSH command stream.
- `max_sftp_upload_bytes`: maximum decoded SFTP upload payload size.
- `max_sftp_download_bytes`: maximum SFTP download payload size.
- `max_sftp_list_entries`: maximum directory entries returned by `jumpserver_sftp_list`.

## Command Policy

Set `ssh_command_policy_mode` to:

- `none`: allow all commands.
- `blacklist`: block commands matching `ssh_command_policy_patterns`.
- `whitelist`: only allow commands matching `ssh_command_policy_patterns`.

Examples:

```txt
ssh_command_policy_mode=blacklist
ssh_command_policy_patterns=rm -rf /,shutdown*,reboot*
```

```txt
ssh_command_policy_mode=whitelist
ssh_command_policy_patterns=df *,free *,uptime,whoami
```

These string patterns are a guardrail, not a shell sandbox. Whitelist mode rejects common shell control and expansion syntax, but strict command patterns are still recommended. Keep JumpServer permissions scoped and avoid treating blacklist mode as the only safety boundary.

## Security Notes

These tools perform high-privilege operations through JumpServer. Keep JumpServer gateway credentials scoped, protect the MCP endpoint with `api_key` when exposed beyond localhost, configure `ssh_gateway_known_hosts_path` or system `known_hosts` for gateway host key verification, and use JumpServer's built-in audit logs for operation review.

For AI clients, see [docs/ai-mcp-ssh-usage.md](docs/ai-mcp-ssh-usage.md).
