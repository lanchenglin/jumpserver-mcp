# JumpServer SSH/SFTP MCP — 工具调用文档

本分支（`feature/ssh-only`）仅暴露 SSH/SFTP 相关工具，不包含 REST API 工具。共 5 个工具。

---

## 1. MCP 接入

### SSE 端点

```
http://<host>:8099/sse
```

### MCP 客户端配置示例

```json
{
  "type": "sse",
  "url": "http://127.0.0.1:8099/sse"
}
```

### Docker 部署

```bash
docker pull harbor.gillion.com.cn/base/jumpserver-ssh-sftp:latest

docker run -d \
  --name jumpserver-mcp \
  --network host \
  --env-file .env \
  --restart unless-stopped \
  harbor.gillion.com.cn/base/jumpserver-ssh-sftp:latest
```

---

## 2. 环境配置（.env）

```env
# JumpServer 地址
jumpserver_url=http://<your-jumpserver-host>

# 认证（Access Key 优先）
access_key_id=<your-access-key-id>
access_key_secret=<your-access-key-secret>

# SSH 网关（JumpServer 本身就是 SSH 代理）
ssh_gateway_host=<your-jumpserver-host>
ssh_gateway_port=2222
ssh_gateway_username=<your-username>
ssh_gateway_password=<your-password>
default_system_user=root

# 可选：API 认证保护
# api_key=<your-api-key>
```

---

## 3. 工具列表

### 3.1 jumpserver_check_host

检查指定资产主机是否可达（通过 SSH 网关连接测试）。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP，例如 `192.168.1.100` |
| `system_user` | 否 | 系统用户名，默认 `default_system_user` |

**请求示例：**

```json
{
  "asset_ip": "192.168.1.100"
}
```

**响应示例：**

```json
{
  "success": true,
  "data": {
    "asset_ip": "192.168.1.100",
    "system_user": "root",
    "reachable": true
  }
}
```

---

### 3.2 jumpserver_ssh_command

通过 JumpServer SSH 网关在指定资产上执行 shell 命令。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP |
| `command` | 是 | 要执行的 shell 命令，例如 `df -h` |
| `system_user` | 否 | 系统用户名，默认 `default_system_user` |

**请求示例：**

```json
{
  "asset_ip": "192.168.1.100",
  "command": "df -h"
}
```

**响应示例：**

```json
{
  "success": true,
  "data": {
    "stdout": "Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1       100G   33G   67G  33% /",
    "stderr": "",
    "output": "STDOUT:\nFilesystem      Size  Used Avail Use% Mounted on\n/dev/sda1       100G   33G   67G  33% /",
    "exit_status": 0,
    "truncated": false
  }
}
```

---

### 3.3 jumpserver_sftp_upload

通过 SFTP 将内容上传到指定资产。提供 `content`（文本）或 `content_base64`（二进制）二选一。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP |
| `remote_path` | 是 | 远程文件路径，例如 `/tmp/hello.txt` |
| `content` | 否 | 文本内容（UTF-8）；与 `content_base64` 二选一 |
| `content_base64` | 否 | 二进制内容（Base64 编码）；与 `content` 二选一 |
| `system_user` | 否 | 系统用户名，默认 `default_system_user` |

**请求示例：**

```json
{
  "asset_ip": "192.168.1.100",
  "remote_path": "/tmp/hello.txt",
  "content": "Hello World"
}
```

**响应示例：**

```json
{
  "success": true,
  "data": {
    "remote_path": "/tmp/hello.txt",
    "bytes": 11
  }
}
```

---

### 3.4 jumpserver_sftp_download

从指定资产下载文件内容。文本文件返回 UTF-8，二进制文件返回 Base64。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP |
| `remote_path` | 是 | 远程文件路径 |
| `system_user` | 否 | 系统用户名，默认 `default_system_user` |

**请求示例：**

```json
{
  "asset_ip": "192.168.1.100",
  "remote_path": "/etc/hostname"
}
```

**响应示例（文本文件）：**

```json
{
  "success": true,
  "data": {
    "remote_path": "/etc/hostname",
    "encoding": "text",
    "content": "web-server-01"
  }
}
```

---

### 3.5 jumpserver_sftp_list

列出指定资产远程目录下的文件和子目录。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP |
| `remote_path` | 否 | 远程目录路径，默认 `.` |
| `system_user` | 否 | 系统用户名，默认 `default_system_user` |

**请求示例：**

```json
{
  "asset_ip": "192.168.1.100",
  "remote_path": "/var/log"
}
```

**响应示例：**

```json
{
  "success": true,
  "data": {
    "remote_path": "/var/log",
    "entries": [
      {"name": "syslog", "size": 1048576, "type": "file"},
      {"name": "nginx", "size": 4096, "type": "dir"}
    ],
    "truncated": false
  }
}
```

---

## 4. 通用说明

### 响应格式

所有工具统一返回 JSON：

```json
{
  "success": true,
  "error": null,
  "code": "OK",
  "message": "OK",
  "data": { ... }
}
```

失败时：

```json
{
  "success": false,
  "error": "错误描述",
  "code": "CONNECTION_ERROR",
  "message": "错误描述",
  "data": {}
}
```

### 错误码

| code | 说明 |
|------|------|
| `INVALID_ARGUMENT` | 参数无效 |
| `COMMAND_BLOCKED` | 命令被策略阻止 |
| `CONNECTION_ERROR` | SSH 连接失败 |
| `EXECUTION_ERROR` | 执行异常 |
| `PAYLOAD_TOO_LARGE` | 文件超出大小限制 |

### 命令策略

通过 `.env` 配置命令执行策略：

```env
# none: 不限制（默认）
# blacklist: 黑名单模式，匹配的命令禁止执行
# whitelist: 白名单模式，仅允许匹配的命令
ssh_command_policy_mode=none
ssh_command_policy_patterns=rm *,shutdown,halt
```

### 大小限制

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `max_command_output_bytes` | 1MB | 命令输出截断 |
| `max_sftp_upload_bytes` | 10MB | 上传文件大小限制 |
| `max_sftp_download_bytes` | 10MB | 下载文件大小限制 |
| `max_sftp_list_entries` | 1000 | 目录列表条目上限 |
