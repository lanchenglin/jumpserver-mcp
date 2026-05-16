# JumpServer MCP：REST API 工具调用说明

本文档面向接入本 MCP 的 AI 客户端，说明如何通过 MCP 调用 JumpServer REST API 工具。

本服务从 JumpServer OpenAPI `swagger.json` 自动生成 MCP 工具，用于资产管理、用户管理等 JumpServer API 操作。

---

## 1. MCP 连接配置

```json
{
  "type": "sse",
  "url": "http://127.0.0.1:8099/sse"
}
```

若配置了 `api_key` 保护，需在 MCP 客户端 headers 中携带：

```json
{
  "type": "sse",
  "url": "http://<MCP_HOST>:8099/sse",
  "headers": {
    "Authorization": "Bearer <api_key>"
  }
}
```

---

## 2. 工具来源

服务启动时读取 JumpServer OpenAPI schema：

```txt
http://<your-jumpserver-host>/api/swagger.json
```

解析每个 API 操作（path + method）并注册为 MCP tool。运行时 MCP 工具调用会代理到 JumpServer REST API。

### Swagger 降级策略

| 优先级 | 来源 | 说明 |
|--------|------|------|
| 1 | 远程拉取 | 认证成功后缓存到本地 |
| 2 | 本地缓存 | `jumpserver_mcp_server/.cache/swagger.json` |
| 3 | 内置 fallback | 覆盖 26 个核心 API（资产、用户、权限、会话等） |

即使 JumpServer 认证暂时不可用，服务仍可正常启动。

---

## 3. JumpServer API 认证

支持两种认证方式：

| 配置 | 说明 |
|------|------|
| `access_key_id` + `access_key_secret` | JumpServer Access Key 签名认证（HMAC-SHA256），**ID 和 Secret 必须是同一对**，优先使用 |
| `api_token` | Bearer token 认证（临时，1 天过期） |

如果同时配置 Access Key 和 Bearer token，服务优先使用 Access Key。

`jms_org_id` 保留兼容；配置后会作为 `X-JMS-ORG` 请求头发送给 JumpServer API。

---

## 4. 默认地址

| 配置 | 默认值 |
|------|--------|
| `jumpserver_url` | `http://<your-jumpserver-host>` |
| `swagger_url` | `<jumpserver_url>/api/swagger.json` |
| `api_base_url` | `<jumpserver_url>/api/v1` |

可通过 `.env` 显式覆盖 `swagger_url` 和 `api_base_url`。

---

## 5. 使用注意

1. MCP 工具由 JumpServer OpenAPI 动态生成，工具列表以当前 schema 为准。
2. AI 客户端执行资产、用户等管理操作前，应确认 JumpServer API 权限范围。
3. 建议对外暴露 MCP 服务时配置 `api_key`。
