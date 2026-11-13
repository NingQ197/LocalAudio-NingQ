# Linux 部署指南

[返回首页](../README.md) · [常见问题](TROUBLESHOOTING.md)

支持 Debian 12 / 13 等 Linux 系统，使用常规 rootful Docker Engine。发行包镜像为 **linux/amd64**；其他架构可选择源码构建。默认 IPv4，也可使用双栈或 IPv6-only。

## 准备环境

需要 Docker Engine、Docker Compose v2、OpenSSL、Python 3；解压发行包还需要 unzip。IPv6-only 覆盖文件使用 Compose 的 `!override`，需要 **Compose v2.24.4 或更新版本**。

命令示例使用 `sudo`。以 root 登录、系统未安装 sudo 时，可直接执行去掉 `sudo` 后的命令。

已安装 Docker 的服务器补齐依赖即可：

```sh
sudo apt update
sudo apt install -y ca-certificates openssl python3 unzip
sudo docker compose version
```

新装 Debian 可按 [Docker 官方指南](https://docs.docker.com/engine/install/debian/)添加软件源：

```sh
sudo apt update
sudo apt install -y ca-certificates curl openssl python3 unzip
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

现有 Docker 来自其他软件源时，安装步骤以官方指南中的迁移说明为准。

## A：下载发行包，离线导入镜像

适合服务器访问 GitHub 较慢的情况。在本机下载，再通过 scp 或 SFTP 上传；服务器无需安装 Git，也无需下载 GitHub 源码或构建依赖。

### 1. 在本机下载和上传

打开 [v2.1.0 Release](https://github.com/NingQ197/LocalAudio-NingQ/releases/tag/v2.1.0)，下载 `LocalAudio-Server.zip` 和 `SHA256SUMS.txt`，放在同一目录。

本机终端执行，替换账号、地址和上传目录：

```sh
scp LocalAudio-Server.zip SHA256SUMS.txt user@your-server:/home/user/
```

使用 IPv6 字面地址连接时，加上方括号：

```sh
scp LocalAudio-Server.zip SHA256SUMS.txt 'user@[2001:db8::10]:/home/user/'
```

`2001:db8::10` 是文档示例地址，替换为服务器实际公网 IPv6。

也可以用 SFTP 工具上传这两个文件。服务端包已包含 Docker 镜像和部署文件；下载项中的 `Source code (zip)`、`Source code (tar.gz)` 是 GitHub 自动生成的纯源码，不包含镜像。

### 2. 在服务器校验和解压

进入上传目录后执行：

```sh
sha256sum -c SHA256SUMS.txt
unzip -q LocalAudio-Server.zip
cd LocalAudio-Server
sha256sum -c LocalAudio-Server.tar.gz.sha256
sudo docker load -i LocalAudio-Server.tar.gz
sudo docker image inspect localaudio-ningq:local
```

前一次校验对应完整 ZIP，后一次校验对应包内镜像。两次都显示 `OK` 后继续。镜像标签为 `localaudio-ningq:local`。

### 3. 填写配置

```sh
cp .env.example .env
nano .env
```

默认 IPv4 只需修改：

```text
TURN_REALM=你的中继域名
TURN_PUBLIC_IP=你的服务器公网IPv4
```

域名不带协议、路径或端口，`TURN_PUBLIC_IP` 填实际公网 IPv4。域名的 A 记录指向这个 IPv4。双栈或 IPv6-only 的填写方式见下文 [IPv6](#ipv6)。

### 4. 放行端口并启动

云安全组与服务器防火墙同时开放：

| 端口 | 用途 |
| --- | --- |
| `21113/TCP`、`21113/UDP` | STUN / TURN 入口 |
| `49160–49200/UDP` | 媒体中继 |

双栈模式同时设置 IPv4 和 IPv6 规则；IPv6-only 设置对应 IPv6 规则。主机位于 NAT 后时，入口和 UDP 中继范围需同号映射到这台服务器。客户端使用 TURN TCP 时，中继的 UDP 媒体范围仍需放行。

```sh
sudo sh scripts/deploy.sh --no-build
sudo docker compose ps
sudo cat secrets/turn-password
```

`--no-build` 使用刚才导入的镜像，不触发镜像构建。首次启动自动生成永久密码，后续部署沿用。默认用户名为 `localaudio`，可通过 `TURN_USERNAME` 修改。

### 5. 配置插件

```text
STUN:  stun:relay.example.com:21113
TURN:  turn:relay.example.com:21113?transport=udp
       turn:relay.example.com:21113?transport=tcp
用户名: localaudio
密码:   secrets/turn-password 中的内容
```

替换成自己的域名和账号。自动模式优先 P2P；验收中继时选择强制中继，确认选中 `relay`，再检查视频和共享音轨。

## B：从源码构建

服务器需能访问 GitHub、Debian 软件源和 Docker 镜像源：

```sh
sudo apt install -y git
git clone --branch v2.1.0 --depth 1 https://github.com/NingQ197/LocalAudio-NingQ.git
cd LocalAudio-NingQ
cp .env.example .env
nano .env
```

按 A 方案的配置与端口步骤设置后，执行：

```sh
sudo sh scripts/deploy.sh
sudo docker compose ps
sudo cat secrets/turn-password
```

不带 `--no-build` 会先构建镜像，再检查配置和启动容器。源码构建使用当前主机架构。

## IPv6

通过 `.env` 中的 `TURN_IP_MODE` 选择模式，部署脚本自动加载对应 Compose 文件：

| 模式 | 必填公网地址 | 对外端口 |
| --- | --- | --- |
| `ipv4`（默认） | `TURN_PUBLIC_IP` | IPv4 |
| `dual` | `TURN_PUBLIC_IP`、`TURN_PUBLIC_IPV6` | IPv4 和 IPv6 |
| `ipv6` | `TURN_PUBLIC_IPV6` | 仅 IPv6 |

### 双栈

```text
TURN_IP_MODE=dual
TURN_PUBLIC_IP=你的服务器公网IPv4
TURN_PUBLIC_IPV6=你的服务器公网IPv6
```

域名同时设置 A 与 AAAA 记录，分别对应两种公网地址。`TURN_PUBLIC_IPV6` 填裸 IPv6，不加方括号、端口或网卡后缀。

### IPv6-only

```text
TURN_IP_MODE=ipv6
TURN_PUBLIC_IP=
TURN_PUBLIC_IPV6=你的服务器公网IPv6
```

域名使用可达的 AAAA 记录。IPv6-only 不要求公网 IPv4，也不发布 IPv4 入口。客户端必须具备 IPv6 网络，并支持申请和使用 IPv6 relay 候选；仅支持 IPv4 的客户端无法直接使用。

### Docker 网络与启动

`compose.ipv6.yaml` 启用容器 IPv6 网络，默认内部子网为 `fd42:2111:3000::/64`。与现有网络冲突时，可修改 `TURN_DOCKER_IPV6_SUBNET`。`TURN_RELAY_IPV6` 通常留空，自动选择容器实际 IPv6；`TURN_PUBLIC_BIND_IPV6` 默认为 `::`。

镜像基于 coturn 4.18.0，包含支持本容器 ULA 中继互通的局部补丁，范围见[安全机制与验证](AUDIT.md#镜像和依赖)。

Linux 宿主必须具有正常的公网 IPv6 路由，Docker 需支持 IPv6 网络、端口发布和出站转发。DNS AAAA 本身不提供网络连通性。云安全组和主机防火墙需要按 IPv6 地址族放行 `21113/TCP`、`21113/UDP`、`49160–49200/UDP`。

配置后，离线包执行：

```sh
sudo sh scripts/deploy.sh --no-build
```

源码构建执行 `sudo sh scripts/deploy.sh`。已有容器从 IPv4 切换 IPv6 网络模式时，可先使用旧模式对应的 Compose 文件组合执行 `down`，再运行部署脚本重建网络；现有中继连接会断开。

手动 Compose 命令的文件组合：

| 模式 | 文件参数（按表内顺序） |
| --- | --- |
| IPv4 | `-f compose.yaml` |
| 双栈 | `-f compose.yaml -f compose.ipv6.yaml` |
| IPv6-only | `-f compose.yaml -f compose.ipv6.yaml -f compose.ipv6only.yaml` |

例如，IPv6-only 的配置检查和状态查询：

```sh
sudo docker compose -f compose.yaml -f compose.ipv6.yaml -f compose.ipv6only.yaml config --quiet
sudo docker compose -f compose.yaml -f compose.ipv6.yaml -f compose.ipv6only.yaml ps
```

先分别测试 IPv4 与 IPv6 的真实中继连接，再保留实际可用的 DNS 记录。IPv6-only 的兼容范围还取决于客户端 WebRTC 实现和运营商网络。

## 常用参数

| 参数 | 默认值 / 用途 |
| --- | --- |
| `TURN_REALM` | 中继域名，必填 |
| `TURN_IP_MODE` | `ipv4`，可选 `dual`、`ipv6` |
| `TURN_PUBLIC_IP` / `TURN_PUBLIC_IPV6` | 对应地址族的实际公网地址 |
| `TURN_PUBLIC_BIND_IP` / `TURN_PUBLIC_BIND_IPV6` | 宿主发布地址，默认 `0.0.0.0` / `::` |
| `TURN_RELAY_IP` / `TURN_RELAY_IPV6` | 默认留空，自动选择容器实际地址 |
| `TURN_PORT` | `21113`，TCP / UDP 入口 |
| `TURN_MIN_PORT` / `TURN_MAX_PORT` | `49160` / `49200`，UDP 中继范围 |
| `TURN_USERNAME` | `localaudio`，永久账号名 |
| `TURN_PASSWORD_FILE` | `/run/secrets/turn-password` |
| `TURN_USER_QUOTA` / `TURN_TOTAL_QUOTA` | `16` / `128`，账号 / 全服务 allocation 配额 |
| `TURN_MAX_BPS` / `TURN_BPS_CAPACITY` | `12000000` / `100000000`，每 allocation / 全服务字节每秒上限 |
| `TURN_MEMORY_LIMIT` / `TURN_CPU_LIMIT` | `512m` / `2.0`，容器资源上限 |

allocation 是协议连接资源，不等于观众数量。默认端口范围包含 41 个媒体端口，实际容量同时取决于端口、带宽、CPU、内存和客户端连接方式。

## 可选 TLS

WebRTC 媒体采用 DTLS-SRTP。TURN TLS 额外保护客户端到中继的连接，默认公网 TCP 端口为 `5349`。

准备域名对应的有效证书链与未加密私钥，复制到 `certs/`：

```sh
sudo install -d -o root -g 65534 -m 0750 certs
sudo install -o root -g 65534 -m 0644 /你的证书目录/fullchain.pem certs/fullchain.pem
sudo install -o root -g 65534 -m 0640 /你的证书目录/privkey.pem certs/privkey.pem
```

`.env` 设置：

```text
TURN_TLS_ENABLE=1
TURN_TLS_PUBLIC_PORT=5349
```

重新运行部署脚本，并在相应地址族放行公网 TCP 5349。客户端填写：

```text
turns:relay.example.com:5349?transport=tcp
```

脚本会按模式自动加载 TLS 覆盖文件。手动运行 Compose 时，在上面的基础文件组合之后追加：

| 模式 | TLS 文件参数 |
| --- | --- |
| IPv4 | `-f compose.tls.yaml` |
| 双栈 | `-f compose.tls.yaml -f compose.tls.ipv6.yaml` |
| IPv6-only | `-f compose.tls.ipv6.yaml` |

证书需与客户端填写的域名匹配，容器 UID/GID `65534:65534` 需能读取。需要使用公网 TCP 443 时，可将 `TURN_TLS_PUBLIC_PORT` 改为 `443`，容器内仍用 `5349`，前提是宿主对应端口未被占用。证书签发和续期由现有证书服务管理；更新后重新复制并部署即可加载新证书。

## 更新、备份与回滚

实例配置由 `.env`、`secrets/` 和自备 `certs/` 组成，备份这些文件可保留账号与证书。镜像和 Compose 文件决定运行版本。

更新前记录旧镜像并保留旧部署目录：

```sh
sudo docker image inspect localaudio-ningq:local --format '{{.Id}}'
sudo docker tag localaudio-ningq:local localaudio-ningq:rollback
```

将新包解压到新目录，迁移实例配置，再导入镜像并部署。更新会中断现有连接。回滚时使用旧目录、旧配置，并执行：

```sh
sudo docker tag localaudio-ningq:rollback localaudio-ningq:local
sudo sh scripts/deploy.sh --no-build
```

备份内含永久密码和 TLS 私钥，适用与原配置相同的访问权限。

## 验收

先确认容器健康和配置检查通过，再从外网完成一次强制中继共享，确认视频和音轨正常。多观众、退出重入、断线恢复和错误密码拒绝也应在实际网络中检查。双栈分别验证两种地址族；IPv6-only 验证客户端实际取得并使用了 IPv6 relay 候选。
