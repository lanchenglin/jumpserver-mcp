# JumpServer MCP Server

JumpServer MCP Server 通过 MCP 协议暴露 JumpServer 的 REST API 工具，工具列表从 JumpServer OpenAPI `swagger.json` 自动生成。

本版本聚焦于 JumpServer API 操作（资产管理、用户管理等），同时提供自定义 SSH/SFTP 工具。

## 配置 JumpServer 环境文件（.env）

```txt
# JumpServer REST API 地址
jumpserver_url=http://<your-jumpserver-host>
# 可选覆盖；为空时分别使用 <jumpserver_url>/api/v1 与 <jumpserver_url>/api/swagger.json
api_base_url=
swagger_url=

# JumpServer API 认证：优先使用 Access Key，其次使用 Bearer Token
access_key_id=<your-access-key-id>
access_key_secret=<your-access-key-secret>
# api_token=<your-bearer-token>

# 组织 ID（可选；配置后作为 X-JMS-ORG 请求头发送）
jms_org_id=

# 保护 MCP HTTP 接口的 API Key（可选）
api_key=<your-mcp-api-key>

# JumpServer SSH 网关（用于 SSH 命令与 SFTP 工具）
# 注意：SSH 网关就是 JumpServer 自身，直接使用 JumpServer 的登录账号密码
# 连接格式：{gateway_user}@{system_user}@{asset_ip}，通过 JumpServer 的 2222 端口连接
ssh_gateway_host=<your-jumpserver-host>
ssh_gateway_port=2222
ssh_gateway_username=<your-username>
ssh_gateway_password=<your-password>
default_system_user=root
```

将 `.env.example` 复制为 `.env` 并填入实际值。请勿提交 `.env` 文件。

## Docker 启动

```bash
docker run -d -it -p 8099:8099 --env-file .env --name jms_mcp ghcr.io/jumpserver/mcp:latest
```

## 获取 JumpServer API Bearer Token

```shell
TOKEN=$(curl -s -X POST http://<your-jumpserver-host>/api/v1/authentication/auth/ \
  -H "Content-Type: application/json" \
  -d '{
    "username": "<your-username>",
    "password": "<your-password>"
  }' \
  --insecure | jq -r '.token')

echo "你的 Bearer Token: $TOKEN"
```

注意：Bearer Token 有效期为 1 天，建议优先使用 Access Key 认证。

## MCP 服务端配置

```json
{
    "type": "sse",
    "url": "http://127.0.0.1:8099/sse",
    "headers": {
        "Authorization": "Bearer <your-mcp-api-key>"
    }
}
```

若 `api_key` 为空，则省略 `headers`。

## REST API 工具生成

启动时，服务器从以下地址获取 JumpServer OpenAPI：

```txt
http://<your-jumpserver-host>/api/swagger.json
```

若配置了 `swagger_url`，则使用该值。API 基础 URL 默认为：

```txt
http://<your-jumpserver-host>/api/v1
```

若配置了 `api_base_url`，则使用该值。

MCP 工具列表从 JumpServer OpenAPI 自动动态生成，每个 API 操作对应一个 MCP 工具，代理请求到 JumpServer。

若远程 swagger 获取失败（如 Token 过期），服务器会依次回退到本地缓存和内置的核心 API 备用 Schema。认证恢复后会自动获取并缓存最新 Schema。

## 认证

服务器支持两种 JumpServer API 认证方式：

1. **Access Key**：`access_key_id` + `access_key_secret`（推荐，永久有效）
2. **Bearer Token**：`api_token`（临时，1 天过期）

同时配置时优先使用 Access Key。

## 自定义 SSH 和 SFTP 工具

除了从 OpenAPI 自动生成的工具外，还提供通过 JumpServer SSH 网关执行的自定义工具：

- **`jumpserver_ssh_command`** — 在资产上执行 shell 命令（如 `df -h`）
- **`jumpserver_sftp_upload`** — 上传文本或 Base64 内容到远程文件
- **`jumpserver_sftp_download`** — 从远程路径下载文件内容（文本或 Base64）
- **`jumpserver_sftp_list`** — 列出资产目录内容（返回 JSON）

**注意：SSH 网关就是 JumpServer 自身**，连接格式为 `{gateway_user}@{system_user}@{asset_ip}`，通过 JumpServer 的 2222 端口连接。

**警告：** 这些是高权限操作，请确保 SSH 网关账号和资产权限受到严格控制。

更多详情请参阅 [docs/ai-mcp-ssh-usage.md](docs/ai-mcp-ssh-usage.md)，包含四个工具（SSH + SFTP）的完整参数说明和调用示例。

## 安全提示

若 MCP 端点可从 localhost 以外访问，请务必配置 `api_key` 保护。JumpServer API 权限应限制为 AI 客户端所需的最小操作范围。
