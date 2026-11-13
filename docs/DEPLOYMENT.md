# Linux 部署指南

[返回首页](../README.md)

适合 Debian 12 / 13 的常规 rootful Docker 部署。需要公网 IPv4；服务器位于 NAT 后时，入口及中继端口必须做同号映射。以下命令不会修改现有 TS 服务。

## 1. 安装依赖

已安装 Docker Engine 和 Compose v2 时，可以直接安装 Git、OpenSSL、Python 3，再跳到下一步。

未安装 Docker 的 Debian 服务器可按 [Docker 官方说明](https://docs.docker.com/engine/install/debian/)添加软件源：

```sh
sudo apt update
sudo apt install -y ca-certificates curl git openssl python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian %s stable\n' "$(dpkg --print-architecture)" "$VERSION_CODENAME" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker compose version
```

已安装其它来源的 Docker 时，按官方指南处理冲突软件包，不要直接混装。Docker 组具有接近 root 的权限，这里统一使用 `sudo`。

## 2. 下载与配置

```sh
git clone https://github.com/NingQ197/LocalAudio-NingQ.git
cd LocalAudio-NingQ
cp .env.example .env
nano .env
```

| 参数 | 用途与默认值 |
| --- | --- |
| `TURN_REALM` | 自己的中继域名；不带协议、路径、端口 |
| `TURN_PUBLIC_IP` | 实际公网 IPv4，必须修改 |
| `TURN_PUBLIC_BIND_IP` | 宿主发布地址，默认 `0.0.0.0` |
| `TURN_RELAY_IP` | 留空，自动选择容器实际 IPv4 |
| `TURN_PORT` | UDP/TCP 入口，默认 `21113` |
| `TURN_MIN_PORT` / `TURN_MAX_PORT` | UDP 中继范围，默认 `49160` / `49200` |
| `TURN_USERNAME` | 永久账号名，默认 `localaudio` |
| `TURN_PASSWORD_FILE` | 容器内密码路径，保持 `/run/secrets/turn-password` |
| `TURN_USER_QUOTA` | 每个账号的 allocation 上限，默认 `16` |
| `TURN_TOTAL_QUOTA` | 全服务 allocation 上限，默认 `128` |
| `TURN_MAX_BPS` | 每个 allocation 字节/秒限制，默认 `12000000` |
| `TURN_BPS_CAPACITY` | 全服务字节/秒限制，默认 `100000000` |
| `TURN_MEMORY_LIMIT` | 容器内存上限，默认 `512m` |
| `TURN_CPU_LIMIT` | 容器 CPU 上限，默认 `2.0` |

allocation 是协议连接资源，不等于观众数量。实际容量同时受中继端口、带宽、CPU 和内存限制；默认 41 个媒体端口也会限制可同时分配的资源。扩大配额时同步评估端口范围和服务器资源。

默认账号永久有效。可选的 shared-secret 模式用于已有系统兼容，默认部署不使用它，也不需要续签服务。

## 3. 放行并启动

云安全组和主机防火墙同时开放 `21113/UDP`、`21113/TCP`、`49160–49200/UDP`。自定义端口后防火墙也要同步修改；Compose 自动读取同一组端口参数。

```sh
sudo sh scripts/deploy.sh
sudo docker compose ps
sudo cat secrets/turn-password
```

`secrets/turn-password` 首次自动随机生成，后续部署保留。目录权限为 `700`、文件权限为 `600`，属主为容器 UID/GID `65534:65534`；宿主上具有该身份或 root 权限的进程也可读取，服务器本身必须可信。

将用户名和密码填入插件网络设置。地址见[首页](../README.md#4-填入插件)。需要更换密码时，安全地替换该文件、保留文件权限，重新部署并更新客户端。不要将密码写进镜像。

## 可选 TLS

TLS 为客户端到中继的连接增加传输保护；WebRTC 媒体本身仍使用 DTLS-SRTP。普通 `turn:` 与加密 `turns:` 的地址不能混用。

先为中继域名准备有效证书链与未加密私钥。将自己的证书复制到本地专用目录，设置容器可读权限：

```sh
sudo install -d -o root -g 65534 -m 0750 certs
sudo install -o root -g 65534 -m 0644 /你的证书目录/fullchain.pem certs/fullchain.pem
sudo install -o root -g 65534 -m 0640 /你的证书目录/privkey.pem certs/privkey.pem
```

`certs/` 应为普通本地目录，两个文件也应为普通文件。不要直接挂载仅 root 可遍历的证书签发目录，否则容器 UID `65534` 会无法读取。

在 `.env` 设置：

```text
TURN_TLS_ENABLE=1
TURN_TLS_PUBLIC_PORT=5349
```

然后重新运行 `sudo sh scripts/deploy.sh`。脚本会自动加载 `compose.tls.yaml`，映射公网 TCP 端口。云安全组和防火墙需额外放行这个 TCP 端口。客户端填写：

```text
turns:relay.example.com:5349?transport=tcp
```

域名必须与证书匹配。需要公网 TCP 443 时，可将 `TURN_TLS_PUBLIC_PORT` 改为 `443`，容器内仍使用非特权端口 `5349`，同时确认宿主 443 未被其他服务占用。

手动执行 Compose 命令时，使用完整参数：

```sh
sudo docker compose -f compose.yaml -f compose.tls.yaml config --quiet
sudo docker compose -f compose.yaml -f compose.tls.yaml run --rm --no-deps turn --validate-only
sudo docker compose -f compose.yaml -f compose.tls.yaml ps
```

证书签发和续期由服务器管理员管理。续期后重新复制证书及私钥、保留权限并重新部署，再验证实际 TLS 连接。

## 镜像导出和离线导入

在可联网的受信任 Linux 构建机上：

```sh
sudo docker build --no-cache -t localaudio-ningq:local ./server
sudo docker save localaudio-ningq:local | gzip > LocalAudio-Server.tar.gz
sha256sum LocalAudio-Server.tar.gz > LocalAudio-Server.tar.gz.sha256
```

传输镜像包、校验文件和源码中的 Compose / 部署文件到目标服务器，不要打包本地 `.env`、`secrets/` 或证书。目标服务器执行：

```sh
sha256sum -c LocalAudio-Server.tar.gz.sha256
sudo docker load -i LocalAudio-Server.tar.gz
sudo docker image inspect localaudio-ningq:local
sudo sh scripts/deploy.sh --no-build
```

`--no-build` 仍会检查配置、生成或保留本地密码，并启动已导入镜像。镜像架构必须与目标服务器一致；在 amd64 构建机默认得到 amd64 镜像。

## 更新、备份与回滚

更新前在仓库之外安全备份 `.env`、`secrets/` 和自备证书，记录旧镜像 ID，并保留旧源码/Compose。

```sh
sudo docker compose images
sudo docker tag localaudio-ningq:local localaudio-ningq:rollback
sudo sh scripts/deploy.sh
```

更新会中断现有中继连接。回滚时恢复旧配置和 Compose，将 `localaudio-ningq:rollback` 重新标记为 `localaudio-ningq:local`，再运行 `sudo sh scripts/deploy.sh --no-build`。备份包含永久密码，按密钥材料保管。

## 验收

容器 `healthy` 只表示本地 STUN 能回应；`--validate-only` 只检查配置。正式使用前，至少从外网完成一次客户端强制中继共享，确认视频和音轨正常，并测试退出重入、多观众及错误密码拒绝。
