# JumpServer MCP：SSH 命令与 SFTP 文件传输 — AI 调用说明

本文档面向接入本 MCP 的 AI 客户端，说明如何通过 MCP 在 JumpServer 资产上执行 shell 命令及进行 SFTP 文件传输。

本服务只暴露 SSH/SFTP 工具，不暴露 JumpServer OpenAPI 自动生成工具；启动不依赖 JumpServer `swagger.json`。

---

## 1. MCP 连接配置

在 AI 的 MCP 客户端配置中加入本服务（例如 Cursor / Claude / 其他 MCP 客户端）：

```json
{
  "type": "sse",
  "url": "http://127.0.0.1:8099/sse"
}
```

若 MCP 服务部署在其他主机，将 `127.0.0.1` 改为实际地址；若配置了 `api_key` 保护，需在 `headers` 中携带：

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

## 2. 工具名称与用途

| 工具名称 | 用途 |
|----------|------|
| `jumpserver_ssh_command` | 在指定资产上执行 shell 命令，返回 stdout/stderr |
| `jumpserver_sftp_upload` | 通过 SFTP 将文本或 Base64 内容上传到资产上的远程文件 |
| `jumpserver_sftp_download` | 通过 SFTP 从资产上的远程文件下载内容（文本或 Base64） |
| `jumpserver_sftp_list` | 通过 SFTP 列出资产上某目录下的文件与子目录 |

---

## 3. 通用返回格式

所有工具均返回 MCP `TextContent`，其中 `text` 是结构化 JSON 字符串：

```json
{
  "success": true,
  "error": null,
  "code": "OK",
  "message": "OK",
  "data": {}
}
```

失败时：

```json
{
  "success": false,
  "error": "命令被策略阻止",
  "code": "COMMAND_BLOCKED",
  "message": "命令被策略阻止",
  "data": {}
}
```

常见错误码：

| code | 含义 |
|------|------|
| `INVALID_ARGUMENT` | 参数缺失或无效 |
| `COMMAND_BLOCKED` | 命令被白名单/黑名单策略阻止 |
| `CONNECTION_ERROR` | SSH 网关连接失败 |
| `EXECUTION_ERROR` | SSH/SFTP 操作执行失败 |
| `PAYLOAD_TOO_LARGE` | 命令输出、上传内容或下载内容超过服务端限制 |
| `UNKNOWN_TOOL` | 工具名称不存在 |

---

## 4. SSH 命令工具：jumpserver_ssh_command

### 4.1 输入参数

| 参数名        | 类型   | 必填 | 说明 |
|---------------|--------|------|------|
| `asset_ip`    | string | 是   | 目标资产 IP，例如 `192.168.1.100` |
| `command`     | string | 是   | 要执行的 shell 命令，例如 `df -h`、`whoami`、`ls -la /tmp` |
| `system_user` | string | 否   | 在目标资产上使用的系统用户名；不传则使用服务端配置的默认用户（通常为 `root`） |

### 4.2 调用示例

- 查看磁盘：`{"asset_ip":"<资产IP>","command":"df -h"}`
- 指定用户：`{"asset_ip":"<资产IP>","system_user":"root","command":"cat /etc/hostname"}`
- 多条命令：`{"asset_ip":"<资产IP>","command":"uptime; free -h"}`

### 4.3 返回 data

```json
{
  "stdout": "...",
  "stderr": "...",
  "output": "STDOUT:\n...",
  "exit_status": 0,
  "truncated": false
}
```

`ssh_command_timeout` 控制命令执行超时，`ssh_connect_timeout` 控制 SSH 建连超时。`max_command_output_bytes` 控制 stdout/stderr 单路返回上限；超出时返回截断内容并设置 `truncated: true`。

---

## 5. SFTP 上传：jumpserver_sftp_upload

| 参数名         | 类型   | 必填 | 说明 |
|----------------|--------|------|------|
| `asset_ip`     | string | 是   | 目标资产 IP |
| `remote_path`  | string | 是   | 远程文件路径；可为相对路径（如 `hello.txt`）或绝对路径 |
| `content`      | string | 否*  | 要写入的文本内容（UTF-8）；与 `content_base64` 二选一 |
| `content_base64` | string | 否* | 要写入的二进制内容（Base64）；与 `content` 二选一 |
| `system_user`  | string | 否   | 系统用户名，默认 root |

\* `content` 与 `content_base64` 至少提供一个。

示例：`{"asset_ip":"<资产IP>","remote_path":"hello.txt","content":"Hello from MCP\n"}`

成功返回 data：

```json
{"remote_path":"hello.txt","bytes":15}
```

上传内容大小受 `max_sftp_upload_bytes` 限制。

---

## 6. SFTP 下载：jumpserver_sftp_download

| 参数名        | 类型   | 必填 | 说明 |
|---------------|--------|------|------|
| `asset_ip`    | string | 是   | 目标资产 IP |
| `remote_path` | string | 是   | 远程文件路径；建议先用 list 查看可用路径，再用相对路径或存在的绝对路径 |
| `system_user` | string | 否   | 系统用户名，默认 root |

文本文件返回：

```json
{"remote_path":"hello.txt","encoding":"text","content":"Hello\n"}
```

二进制文件返回：

```json
{"remote_path":"file.bin","encoding":"base64","content":"..."}
```

下载内容大小受 `max_sftp_download_bytes` 限制。

---

## 7. SFTP 列目录：jumpserver_sftp_list

| 参数名        | 类型   | 必填 | 说明 |
|---------------|--------|------|------|
| `asset_ip`    | string | 是   | 目标资产 IP |
| `remote_path` | string | 否   | 远程目录路径，默认 `.`（当前 SFTP 根） |
| `system_user` | string | 否   | 系统用户名，默认 root |

返回 data：

```json
{
  "remote_path": ".",
  "entries": [
    {"name":"文件名","size":123,"type":"file"}
  ],
  "truncated": false
}
```

---

## 8. 连接复用说明

MCP 服务端会按 `asset_ip + system_user` 复用 SSH 连接。复用前会执行轻量健康检查，断开或超时后自动重建。默认空闲回收为 25 分钟，低于 JumpServer 服务端 30 分钟无 IO 自动断连。

服务端配置：

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `ssh_pool_max_connections` | `10` | 最大池化 SSH 连接数 |
| `ssh_pool_idle_timeout` | `1500` | 空闲连接回收秒数，默认 25 分钟，低于 JumpServer 服务端 30 分钟无 IO 自动断连 |
| `ssh_connect_timeout` | `30` | SSH 建连超时秒数 |
| `ssh_health_check_interval` | `60` | 同一复用连接两次命令式健康检查之间的最小秒数 |
| `ssh_command_timeout` | `30` | SSH 命令执行超时秒数 |
| `mcp_worker_threads` | `8` | 同时执行阻塞型 SSH/SFTP 工具调用的最大线程数 |
| `max_command_output_bytes` | `1048576` | stdout/stderr 单路最大返回字节数 |
| `max_sftp_upload_bytes` | `10485760` | SFTP 上传最大字节数 |
| `max_sftp_download_bytes` | `10485760` | SFTP 下载最大字节数 |
| `max_sftp_list_entries` | `1000` | SFTP 列目录最大返回条目数 |

---

## 9. 命令安全策略

服务端可配置命令白名单/黑名单：

```txt
ssh_command_policy_mode=blacklist
ssh_command_policy_patterns=rm -rf /,shutdown*,reboot*
```

或：

```txt
ssh_command_policy_mode=whitelist
ssh_command_policy_patterns=df *,free *,uptime,whoami
```

`ssh_command_policy_patterns` 使用逗号分隔，支持 shell 通配符。该策略是服务端调用护栏，不是完整 shell 沙箱；白名单模式会拒绝常见 shell 控制与扩展语法，但仍建议配置严格命令模式，并依赖 JumpServer 授权、审批和审计控制高危操作。

---

## 10. 使用注意（给 AI 的约束建议）

1. **资产 IP 必填**：`asset_ip` 须为 JumpServer 已纳管资产 IP。
2. **SSH 一次一条命令**：可将多条用 `;` 或 `&&` 拼成一条。
3. **高危命令**：避免未确认的 rm、格式化、关机等；优先只读命令。
4. **SFTP 路径**：`remote_path` 为资产上的绝对或相对路径；上传会覆盖已存在文件。
5. **权限与审计**：由 JumpServer 网关账号授权控制，操作审计使用 JumpServer 服务端已有审计日志。

---

## 11. 小结（供 AI 快速检索）

- **连接**：SSE URL `http://<host>:8099/sse`，可选 Header `Authorization: Bearer <api_key>`。
- **工具**：只包含 `jumpserver_ssh_command`、`jumpserver_sftp_upload`、`jumpserver_sftp_download`、`jumpserver_sftp_list`。
- **公共参数**：`asset_ip`（必填）、`system_user`（可选，默认 root）。
- **返回**：统一 JSON 文本，读取 `success/code/message/data` 判断结果。
