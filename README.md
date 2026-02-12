# JumpServer MCP Server

## Configure JumpServer Environment File (.env)

```txt
# JumpServer base URL
jumpserver_url=http://jumpserverhost

# Optional: Bearer token to access the JumpServer Swagger Json API
api_token=xxxxxxx

# Optional: Access Key authentication for JumpServer API
access_key_id=your-access-key-id
access_key_secret=your-access-key-secret

# Optional: JumpServer organization ID
jms_org_id=00000000-0000-0000-0000-000000000002

# Optional: Protect MCP HTTP endpoint with an API key
api_key=your-mcp-http-api-key

# Optional: JumpServer SSH gateway (for SSH command execution tool)
ssh_gateway_host=your-ssh-gateway-host
ssh_gateway_port=2222
ssh_gateway_username=your-gateway-username
ssh_gateway_password=your-gateway-password
default_system_user=root
```

Copy `.env.example` to `.env` and fill in your values. Do not commit `.env` (it is in `.gitignore`).

## Start Docker Container

```bash
docker run -d -it -p 8099:8099 --env-file .env --name jms_mcp ghcr.io/jumpserver/mcp:latest
```

## Create JumpServer API Bearer Token for MCP Server

```shell

TOKEN=$(curl -s -X POST http://jumpserver_host/api/v1/authentication/auth/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "xxxx"
  }' \
  --insecure | jq -r '.token')

echo "Your Bearer token: $TOKEN"

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

## Custom SSH and SFTP Tools

In addition to the tools generated from the JumpServer OpenAPI schema, this MCP server exposes
custom tools that use the JumpServer SSH gateway (same config as `ssh_gateway_*` in `.env`):

- **`jumpserver_ssh_command`** — execute a shell command on an asset (e.g. `df -h`).
- **`jumpserver_sftp_upload`** — upload text or Base64 content to a remote file path.
- **`jumpserver_sftp_download`** — download file content from a remote path (text or Base64).
- **`jumpserver_sftp_list`** — list directory contents on an asset (returns JSON).

### jumpserver_ssh_command

Input schema:

- `asset_ip` (string, required): Target asset IP (e.g. `192.168.1.100`)
- `system_user` (string, optional): System username on the target asset (default: `default_system_user` from `.env`)
- `command` (string, required): Shell command to execute (for example `df -h`)

This tool uses the SSH gateway configuration from `.env` (`ssh_gateway_host`, `ssh_gateway_port`,
`ssh_gateway_username`, `ssh_gateway_password`) to open an SSH session to the asset and run
the requested command. The result is returned as plain text (stdout and stderr).

**Warning:** These are high‑privilege operations. Make sure the SSH gateway account and asset
permissions are strictly controlled.

For AI clients: see [docs/ai-mcp-ssh-usage.md](docs/ai-mcp-ssh-usage.md) for connection config, all four tools (SSH + SFTP), parameters, and examples.
