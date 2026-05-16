# JumpServer MCP：REST API 工具调用说明

本文档面向接入本 MCP 的 AI 客户端，说明如何通过 MCP 调用 JumpServer REST API 工具。

本服务从 JumpServer OpenAPI `swagger.json` 自动生成 MCP 工具，用于资产管理、用户管理等 JumpServer API 操作；不提供 SSH/SFTP 工具。

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
http://jumpserver.ks.gillion.com.cn/api/swagger.json
```

然后通过 `fastapi-mcp` 自动转换为 MCP 工具。实际工具名称和参数由 JumpServer OpenAPI 的 operationId、path、method 和 schema 决定。

---

## 3. JumpServer API 认证

支持两种认证方式：

| 配置 | 说明 |
|------|------|
| `access_key_id` + `access_key_secret` | JumpServer Access Key 签名认证，优先使用 |
| `api_token` | Bearer token 认证 |

如果同时配置 Access Key 和 Bearer token，服务优先使用 Access Key。

`jms_org_id` 保留兼容；配置后会作为 `X-JMS-ORG` 请求头发送给 JumpServer API。

---

## 4. 默认地址

| 配置 | 默认值 |
|------|--------|
| `jumpserver_url` | `http://jumpserver.ks.gillion.com.cn` |
| `swagger_url` | `<jumpserver_url>/api/swagger.json` |
| `api_base_url` | `<jumpserver_url>/api/v1` |

可通过 `.env` 显式覆盖 `swagger_url` 和 `api_base_url`。

---

## 5. 使用注意

1. 当前 Bearer token 已知可能过期；若 swagger 拉取返回 401，需要更新认证配置。
2. MCP 工具由 JumpServer OpenAPI 自动生成，工具列表以当前 JumpServer 服务端 schema 为准。
3. AI 客户端执行资产、用户等管理操作前，应确认 JumpServer API 权限范围。
4. 建议对外暴露 MCP 服务时配置 `api_key`。
