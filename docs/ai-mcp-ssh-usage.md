# JumpServer MCP：SSH 命令与 SFTP 文件传输 — AI 调用说明

本文档面向接入本 MCP 的 AI 客户端，说明如何通过 MCP 在 JumpServer 资产上执行 shell 命令及进行 SFTP 文件传输。

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

## 3. SSH 命令工具：jumpserver_ssh_command

### 3.1 输入参数

| 参数名        | 类型   | 必填 | 说明 |
|---------------|--------|------|------|
| `asset_ip`    | string | 是   | 目标资产 IP，例如 `192.168.1.100` |
| `command`     | string | 是   | 要执行的 shell 命令，例如 `df -h`、`whoami`、`ls -la /tmp` |
| `system_user` | string | 否   | 在目标资产上使用的系统用户名；不传则使用服务端配置的默认用户（通常为 `root`） |

### 3.2 调用示例

- 查看磁盘：`{"asset_ip":"<资产IP>","command":"df -h"}`
- 指定用户：`{"asset_ip":"<资产IP>","system_user":"root","command":"cat /etc/hostname"}`
- 多条命令：`{"asset_ip":"<资产IP>","command":"uptime; free -h"}`

---

## 4. SFTP 上传：jumpserver_sftp_upload

| 参数名         | 类型   | 必填 | 说明 |
|----------------|--------|------|------|
| `asset_ip`     | string | 是   | 目标资产 IP |
| `remote_path`  | string | 是   | 远程文件路径；可为相对路径（如 `hello.txt`）或绝对路径 |
| `content`      | string | 否*  | 要写入的文本内容（UTF-8）；与 `content_base64` 二选一 |
| `content_base64` | string | 否* | 要写入的二进制内容（Base64）；与 `content` 二选一 |
| `system_user`  | string | 否   | 系统用户名，默认 root |

\* `content` 与 `content_base64` 至少提供一个。

**注意**：JumpServer SFTP 可能是 chroot 视图，绝对路径（如 `/tmp/xxx`）可能不存在。若报错 “file does not exist”，请改用相对路径（如 `hello.txt` 表示当前目录下文件）。

示例：`{"asset_ip":"<资产IP>","remote_path":"hello.txt","content":"Hello from MCP\n"}`

---

## 5. SFTP 下载：jumpserver_sftp_download

| 参数名        | 类型   | 必填 | 说明 |
|---------------|--------|------|------|
| `asset_ip`    | string | 是   | 目标资产 IP |
| `remote_path` | string | 是   | 远程文件路径；建议先用 list 查看可用路径，再用相对路径或存在的绝对路径 |
| `system_user` | string | 否   | 系统用户名，默认 root |

返回：文本文件为 UTF-8 文本；二进制文件为 `Base64:\n` 开头的 Base64 字符串。若路径不存在会返回 `Error: 下载失败 - ...`。

示例：`{"asset_ip":"<资产IP>","remote_path":"hello.txt"}`

---

## 6. SFTP 列目录：jumpserver_sftp_list

| 参数名        | 类型   | 必填 | 说明 |
|---------------|--------|------|------|
| `asset_ip`    | string | 是   | 目标资产 IP |
| `remote_path` | string | 否   | 远程目录路径，默认 `.`（当前 SFTP 根） |
| `system_user` | string | 否   | 系统用户名，默认 root |

返回：JSON 数组，每项为 `{"name":"文件名","size":字节数,"type":"file"|"dir"}`。建议先不传 `remote_path` 或传 `.` 查看根下列表，再决定上传/下载路径。

示例：`{"asset_ip":"<资产IP>"}` 或 `{"asset_ip":"<资产IP>","remote_path":"."}`

---

## 7. 返回格式（通用）

- 所有工具均返回 **文本内容**（MCP `TextContent`）。
- **jumpserver_ssh_command**：`STDOUT:` / `STDERR:` 后跟命令输出。
- **jumpserver_sftp_upload**：成功为 `OK: 已写入 <remote_path>`；失败为错误信息。
- **jumpserver_sftp_download**：文件内容（文本或 `Base64:\n...`）。
- **jumpserver_sftp_list**：JSON 数组字符串。
- 连接或参数错误时，返回内容中会包含错误信息。

---

## 8. 使用注意（给 AI 的约束建议）

1. **资产 IP 必填**：`asset_ip` 须为 JumpServer 已纳管资产 IP。
2. **SSH 一次一条命令**：可将多条用 `;` 或 `&&` 拼成一条。
3. **高危命令**：避免未确认的 rm、格式化、关机等；优先只读命令。
4. **SFTP 路径**：`remote_path` 为资产上的绝对或相对路径；上传会覆盖已存在文件。
5. **权限**：由 JumpServer 网关账号对目标资产的授权决定。

---

## 9. 小结（供 AI 快速检索）

- **连接**：SSE URL `http://<host>:8099/sse`，可选 Header `Authorization: Bearer <api_key>`。
- **工具**：`jumpserver_ssh_command`（执行命令）、`jumpserver_sftp_upload`（上传）、`jumpserver_sftp_download`（下载）、`jumpserver_sftp_list`（列目录）。
- **公共参数**：`asset_ip`（必填）、`system_user`（可选，默认 root）。
- **返回**：均为纯文本（含 STDOUT/STDERR、OK 消息、文件内容或 JSON 列表）。
