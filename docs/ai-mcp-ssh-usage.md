# JumpServer MCP：SSH/SFTP 工具调用说明

本文档面向接入本 MCP 的 AI 客户端，说明如何通过 MCP 使用 SSH 命令执行和 SFTP 文件操作工具。

---

## 1. 前置配置

SSH/SFTP 工具需要在 `.env` 中配置 JumpServer SSH 网关信息：

```env
ssh_gateway_host=<your-jumpserver-host>
ssh_gateway_port=2222
ssh_gateway_username=<your-username>        # JumpServer 登录用户名
ssh_gateway_password=<your-password>        # JumpServer 登录密码
default_system_user=root                    # 默认系统用户
```

JumpServer 本身就是 SSH 代理服务器，连接格式为 `{gateway_user}@{system_user}@{asset_ip}`，通过 `<jumpserver-host>:2222` 连接。

**注意：** 网关账号密码是服务端配置，调用工具时无需传入。

---

## 2. 工具列表

### jumpserver_ssh_command

通过 JumpServer SSH 网关在指定资产上执行 shell 命令。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP，例如 `192.168.1.100` |
| `command` | 是 | 要执行的 shell 命令，例如 `df -h` |
| `system_user` | 否 | 目标资产上的系统用户名，默认使用配置中的 `default_system_user` |

**示例：**

```json
{
  "asset_ip": "192.168.1.100",
  "command": "df -h"
}
```

### jumpserver_sftp_upload

通过 SFTP 将内容上传到指定资产的远程路径。提供 `content`（文本）或 `content_base64`（二进制）二选一。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP |
| `remote_path` | 是 | 远程文件路径，例如 `/tmp/hello.txt` |
| `content` | 否 | 要写入的文本内容（UTF-8）；与 `content_base64` 二选一 |
| `content_base64` | 否 | 要写入的二进制内容（Base64 编码）；与 `content` 二选一 |
| `system_user` | 否 | 默认使用 `default_system_user` |

**示例：**

```json
{
  "asset_ip": "192.168.1.100",
  "remote_path": "/tmp/hello.txt",
  "content": "Hello World"
}
```

### jumpserver_sftp_download

从指定资产下载文件内容。返回文本或 Base64（二进制时）。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP |
| `remote_path` | 是 | 远程文件路径，例如 `/etc/hostname` |
| `system_user` | 否 | 默认使用 `default_system_user` |

**示例：**

```json
{
  "asset_ip": "192.168.1.100",
  "remote_path": "/etc/hostname"
}
```

### jumpserver_sftp_list

列出指定资产远程目录下的文件和子目录。

**参数：**

| 参数 | 必填 | 说明 |
|------|------|------|
| `asset_ip` | 是 | 资产 IP |
| `remote_path` | 是 | 远程目录路径，例如 `/var/log` |
| `system_user` | 否 | 默认使用 `default_system_user` |

**示例：**

```json
{
  "asset_ip": "192.168.1.100",
  "remote_path": "/var/log"
}
```

---

## 3. 使用注意

1. 这是高权限操作，请谨慎使用，建议在执行前确认命令安全性。
2. JumpServer 服务端有无 IO 自动断连超时设置（可在 JumpServer 管理后台配置）。
3. 支持命令策略控制（白名单/黑名单模式），通过 `.env` 中的 `ssh_command_policy_mode` 和 `ssh_command_policy_patterns` 配置。
