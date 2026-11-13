<p align="center">
  <img src="docs/assets/cover.svg" width="100%" alt="LocalAudio NingQ — TeamSpeak 屏幕共享中继服务端">
</p>

<p align="center">
  <strong>为 LocalAudio 屏幕共享提供可自行部署的中继。</strong><br>
  TeamSpeak 3 · WebRTC · coturn · Debian / Docker<br>
  <sub>Design by ningq</sub>
</p>

<p align="center">
  <a href="https://github.com/NingQ197/LocalAudio-NingQ/actions/workflows/ci.yaml"><img src="https://github.com/NingQ197/LocalAudio-NingQ/actions/workflows/ci.yaml/badge.svg" alt="Checks"></a>
  &nbsp; <a href="#快速部署">快速部署</a>
  &nbsp;·&nbsp; <a href="docs/DEPLOYMENT.md">Linux 部署指南</a>
  &nbsp;·&nbsp; <a href="docs/TROUBLESHOOTING.md">故障排查</a>
</p>

## 这是做什么的

LocalAudio-NingQ 是 [LocalAudio 插件](https://github.com/NingQ197/LocalAudio-Plugin)的屏幕共享 TURN 中继服务端。两端能直连时优先 P2P；直连困难时，可以使用自己的服务器中继。

- 使用 Docker 部署，支持 Debian 等 Linux 系统。
- 默认入口为 **21113 UDP / TCP**。
- 使用永久用户名和密码，不需要定时续签或联网激活。
- WebRTC 媒体使用 DTLS-SRTP 加密，中继负责转发画面和共享音轨。
- 容器以非 root 运行，限制权限、内存、CPU、连接配额和日志大小。

屏幕采集、分辨率、帧率和观看界面由插件提供。这个服务端不代替 TS 服务器，媒体也不通过 TS 的语音编码流传输。TURN 密码用于授权中继流量；观看权限仍由插件与 TS 频道访问规则决定。

## 快速部署

需要一台有公网 IPv4 的 Linux 服务器，并安装 Docker Engine、Docker Compose v2、Git、OpenSSL 和 Python 3。还没安装 Docker 时，先按 [Linux 部署指南](docs/DEPLOYMENT.md#1-安装依赖)操作。

### 1. 下载并填写配置

```sh
git clone https://github.com/NingQ197/LocalAudio-NingQ.git
cd LocalAudio-NingQ
cp .env.example .env
nano .env
```

先修改这两项，其余可以保持默认：

```text
TURN_REALM=你的中继域名
TURN_PUBLIC_IP=你的服务器公网IPv4
```

`TURN_REALM` 填域名，不加协议或端口；`TURN_PUBLIC_IP` 必须填实际公网 IPv4，不能填域名。域名需解析到这台服务器。

### 2. 放行端口

在云安全组和服务器防火墙同时放行：

| 端口 | 用途 |
| --- | --- |
| `21113/UDP` | STUN / TURN 入口 |
| `21113/TCP` | TURN TCP 入口 |
| `49160–49200/UDP` | TURN 媒体中继 |

**只放行 21113，不能保证中继媒体正常。** `49160–49200` 是媒体分配端口，并不是另外一个客户端地址。不要把整个容器改成 host 网络来绕过配置。

### 3. 构建并启动

```sh
sudo sh scripts/deploy.sh
sudo docker compose ps
```

脚本首次生成随机密码，以后重新运行会保留已有密码。查看自己的密码：

```sh
sudo cat secrets/turn-password
```

密码只发给允许使用中继的人，别把 `.env`、`secrets/`、证书或日志上传到 GitHub。

### 4. 填入插件

在 LocalAudio 屏幕共享的网络设置中填写：

```text
STUN:  stun:relay.example.com:21113
TURN:  turn:relay.example.com:21113?transport=udp
       turn:relay.example.com:21113?transport=tcp
用户名: localaudio
密码:   secrets/turn-password 中的内容
```

将 `relay.example.com` 替换成自己的中继域名；如果改过 `.env` 中的 `TURN_USERNAME`，用户名也要相应修改。保留自动连接可优先 P2P，测试服务器时切换为强制中继，确认连接状态为 `relay` 后再检查音画。

## 已有镜像怎么部署

通过检查的工作流会在 Actions 附件中保留 14 天的 `LocalAudio-Server-amd64` 镜像与校验文件。下载并解压附件后，仍需保留本仓库的 Compose 和配置文件。完成上面的配置与防火墙步骤后：

```sh
sudo docker load -i LocalAudio-Server.tar.gz
sudo docker image ls
sudo sh scripts/deploy.sh --no-build
```

导入镜像应带有 `localaudio-ningq:local` 标签；标签不同时，先用 `docker tag` 将它标记为这个名称。`--no-build` 使用已导入镜像，不重新下载源码构建。

## 常用命令

```sh
sudo docker compose ps
sudo docker compose logs --tail 50 turn
sudo docker compose run --rm --no-deps turn --validate-only
sudo docker compose down
```

启用 TLS 时，部署脚本会自动加入 TLS 端口映射；手动操作 Compose 请按[部署指南](docs/DEPLOYMENT.md#可选-tls)同时加载覆盖文件。变更配置或密码后重新部署会中断当前中继连接。

## 文档

| 文档 | 内容 |
| --- | --- |
| [Linux 部署指南](docs/DEPLOYMENT.md) | 安装依赖、参数、TLS、离线镜像、备份与更新 |
| [故障排查](docs/TROUBLESHOOTING.md) | 486、401、端口、NAT 和连接问题 |
| [安全机制与验证](docs/AUDIT.md) | 鉴权、防护、自动检查与实际验收方法 |
| [安全说明](SECURITY.md) | 信任边界、凭据管理与问题反馈 |
| [第三方声明](server/THIRD_PARTY_NOTICES.txt) | coturn 和 Debian 组件 |

## 开发与验证

```sh
python3 tools/check_publish.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
docker build -t localaudio-ningq:test ./server
LOCAL_AUDIO_TEST_IMAGE=localaudio-ningq:test python3 tools/run_container_checks.py
```

CI 构建真实镜像，验证 UDP / TCP / TLS 鉴权、拒绝匿名和错误密码、受限对端、双向 UDP 中继及运行权限，并对最终镜像执行漏洞扫描。扫描中的可修复高危和严重问题会阻止检查通过；暂时没有修复版本的条目仍会完整列出，不作为零漏洞保证。

本项目使用 [MIT 许可证](LICENSE)。coturn 4.18.0 来自[上游源码](https://github.com/coturn/coturn/tree/4.18.0)，基础镜像和源码均固定摘要；构建时安装 Debian 安全更新。数据库客户端和编译工具不会进入运行镜像。
