# 部署详解

[返回首页](../README.md)

## 配置与持久化

运行时使用根目录 `.env`、`secrets/` 和可选的 `certs/`。这些路径已被 Git 忽略；Docker 构建上下文进一步限制到 `server/` 中五个必要文件。

| 参数 | 作用 |
| --- | --- |
| `TURN_REALM` | 自己的 TURN 鉴权 realm，通常使用中继域名 |
| `TURN_PUBLIC_IP` | 当前中继的真实公网 IPv4；脚本拒绝私网和文档示例地址 |
| `TURN_RELAY_IP` | 留空自动选择容器实际 IPv4；手动指定时必须属于该容器 |
| `TURN_PUBLIC_BIND_IP` | 宿主发布地址，默认 `0.0.0.0` |
| `TURN_PORT` | UDP/TCP 入口，默认 `21113` |
| `TURN_MIN_PORT` / `TURN_MAX_PORT` | UDP 中继端口范围 |
| `TURN_USERNAME` | 静态账号名称 |
| `TURN_PASSWORD_FILE` | 容器内密码文件路径，默认 `/run/secrets/turn-password` |
| `TURN_USER_QUOTA` | 同一账号的 allocation 上限 |
| `TURN_TOTAL_QUOTA` | 全服务 allocation 上限 |
| `TURN_MAX_BPS` | 单 allocation 带宽限制，单位字节/秒 |
| `TURN_BPS_CAPACITY` | 全服务带宽限制，单位字节/秒 |

入口端口与中继范围需要互不重叠。默认 Docker bridge 网络隔离应保持；宿主网络模式会改变受限对端策略的信任边界。

## 密码文件

默认部署使用永久静态 TURN 账号，不需要定时续签。`scripts/deploy.sh` 首次生成随机密码，已有非空文件会保留；空文件和符号链接会被拒绝。

脚本面向常规 rootful Docker：通过 `sudo sh scripts/deploy.sh` 运行，将密码目录和文件设为容器 UID/GID `65534:65534` 可读。密码目录权限 `700`，密码文件权限 `600`，容器只读挂载该目录。

需要更改密码时，先通过本地管理流程替换文件，再重建中继容器并同步客户端。密码更新会影响后续鉴权；备份时保留文件的保密性与权限。

入口源码还保留可选的 TURN shared-secret 鉴权兼容性。这属于 TURN 协议鉴权，不是购买激活。选择该模式时，须清空静态账号变量，独立配置足够强的 shared secret；默认部署脚本与本指南主要覆盖静态账号。

## 可选 TLS

1. 为自己的中继域名准备有效证书链与对应私钥。
2. 将文件保存为 `certs/fullchain.pem`、`certs/privkey.pem`，确保容器 UID `65534` 可读，限制其他账户读取私钥。
3. 在 `.env` 设置 `TURN_TLS_ENABLE=1`。
4. 使用两个 Compose 文件检查和启动：

```sh
docker compose -f compose.yaml -f compose.tls.yaml config --quiet
docker compose -f compose.yaml -f compose.tls.yaml \
  run --rm --no-deps turn --validate-only
docker compose -f compose.yaml -f compose.tls.yaml up -d --build --force-recreate turn
```

TLS 公网 TCP 端口由 `TURN_TLS_PUBLIC_PORT` 控制，映射到容器 `TURN_TLS_PORT`。客户端地址使用 `turns:`，并使域名与证书匹配。证书更新后重建容器以重新加载证书，随后检查实际 TLS 连接。

证书签发、续期及反向代理由部署者管理；仓库保留空的运行路径约定，不附带任何真实证书或私钥。

## 更新与备份

更新前备份 `.env`、`secrets/` 及自备证书，记录当前镜像 ID。拉取审查过的源码，再构建和验证配置；确认可接受连接中断后重建容器。

```sh
docker compose images
docker compose build turn
docker compose run --rm --no-deps turn --validate-only
docker compose up -d --force-recreate turn
docker compose ps
```

备份应存放于仓库之外或被忽略的 `backups/`。需要离线部署时，可在受信任机器构建并通过 `docker save` 导出镜像，再在目标机器 `docker load`；运行配置与凭据继续单独管理。

## 构建边界

基础镜像固定到官方 coturn Debian 镜像摘要。`Dockerfile` 的默认构建仅复制入口脚本、健康检查和受限对端策略，容器使用非 root UID `65534`。

健康检查不代表完整 TURN 媒体路径已贯通。部署验收应包含正确/错误账号鉴权、强制中继音画、多观众、退出重入，以及实际公网防火墙和 NAT 路由。
