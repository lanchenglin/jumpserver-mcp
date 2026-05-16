# JumpServer MCP Server — 项目说明

## 项目用途
JumpServer MCP Server，让 AI 通过 MCP 协议管理 JumpServer 资产。同时提供：
- **REST API 工具**：通过 JumpServer OpenAPI 自动生成（资产管理、用户管理等，555 路径 1093 工具）
- **SSH/SFTP 工具**：`jumpserver_ssh_command`、`jumpserver_sftp_upload/download/list`

## 技术栈
- Python >= 3.11
- FastAPI + fastapi-mcp（SSE 传输）
- paramiko（SSH/SFTP）
- JumpServer OpenAPI swagger.json 自动生成 MCP 工具

## 关键配置（.env）

### 必填
```
jumpserver_url=http://<your-jumpserver-host>
access_key_id=<your-access-key-id>
access_key_secret=<your-access-key-secret>
```

### SSH 网关（就是用 JumpServer 自己的登录凭据）
```
ssh_gateway_host=<your-jumpserver-host>
ssh_gateway_port=2222
ssh_gateway_username=<your-username>           # JumpServer 登录用户名
ssh_gateway_password=<your-password>            # JumpServer 登录密码
default_system_user=root
```

**注意：不需要单独的 SSH 网关凭据。** JumpServer 自己就是 SSH 代理服务器，直接用 JumpServer 的登录账号密码即可。SSH 连接格式：`{gateway_user}@{system_user}@{asset_ip}`，通过 `<jumpserver-host>:2222` 连接。

## 认证方式

### 优先：Access Key（HMAC-SHA256 签名，永久有效）
- `access_key_id`：UUID 格式
- `access_key_secret`：32 位随机字符串
- 获取方式：JumpServer Web → 个人信息 → Access Key

### 兼容：Bearer Token（临时，1 天过期）
- 通过 POST `/api/v1/authentication/auth/` 用用户名密码换取
- 配置为 `api_token=<token>`

## JumpServer 环境信息（示例）
- 资产数：241 台
- API 路径数：555（1093 操作）
- SSH 网关端口：2222
- 30 分钟无 IO 自动断连（服务端控制）

## 启动方式
```bash
cp .env.example .env   # 填写配置
uv sync
uv run main.py         # 监听 0.0.0.0:8099，SSE 端点 /sse
```

## MCP 客户端接入
```json
{
    "type": "sse",
    "url": "http://127.0.0.1:8099/sse"
}
```

## 文件结构
```
jumpserver-mcp/
├── main.py                         # 入口
├── pyproject.toml                  # 依赖（fastapi-mcp, paramiko, httpx）
├── jumpserver_mcp_server/
│   ├── server.py                   # 核心：MCP 服务 + 工具注册 + SSH/SFTP 实现
│   ├── config.py                   # 配置（pydantic-settings，读 .env）
│   └── setup.py                    # 日志配置
├── Dockerfile                      # Docker 部署
├── docs/ai-mcp-ssh-usage.md        # SSH/SFTP 工具使用文档
└── README.md                       # 项目说明
```
