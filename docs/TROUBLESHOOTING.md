# 常见问题

[返回首页](../README.md) · [部署指南](DEPLOYMENT.md)

## 先查看状态

```sh
sudo docker compose ps
sudo docker compose logs --tail 50 turn
sudo docker compose run --rm --no-deps turn --validate-only
```

容器 `healthy` 表示本地 STUN 能响应；配置校验通过表示配置格式有效。两者都不替代公网媒体连接测试。额外启用了 TLS 或 IPv6 覆盖文件时，手动 Compose 命令需使用部署指南中对应的完整文件组合。

## 486：中继分配配额已满

allocation 是一份 TURN 连接资源，不等于一名观众。ICE 候选收集、重连和多名观众都会增加分配；多个客户端共用一个账号时，也共用该账号的配额。

查看 `TURN_USER_QUOTA`、`TURN_TOTAL_QUOTA` 和日志，确认客户端退出后旧连接正常释放。需要扩大容量时，同时调整配额、媒体端口范围和服务器资源，再重新部署。默认 `49160–49200` 只有 41 个媒体端口；仅提高配额不会增加端口或带宽。486 与永久账号的有效期无关。

## STUN 正常，但没有画面

依次核对：

1. 客户端地址、DNS 和入口端口对应实际中继服务器。
2. 云安全组和主机防火墙开放了 `21113/TCP`、`21113/UDP`、`49160–49200/UDP`。
3. `TURN_PUBLIC_IP` 与实际公网 IPv4 一致；NAT 后的媒体端口采用同号映射。
4. 用户名、密码与服务器一致。
5. 测试时选择强制中继，客户端实际选中了 `relay` 候选。

普通 TURN TCP 仅将客户端到中继的传输改为 TCP，服务器的 UDP 媒体中继范围仍需开放。

## 401：用户名或密码不匹配

长期鉴权的首次 401 通常是正常的认证挑战，客户端随后携带 realm、nonce 和完整性信息重试。持续 401 时，核对用户名、密码和 `TURN_REALM`。密码以 `sudo cat secrets/turn-password` 的结果为准。

默认是静态账号；shared-secret 是另一种兼容模式，其管理密钥不能直接当作静态账号密码填写。

## 403：对端地址受限

默认策略限制私网、回环、链路本地等目标。容器自身经过核对的中继 IP 有精确例外，用于同服务 allocation 互通。

核对容器网络和 relay 地址是否仍与部署配置一致。默认 bridge 与单用途容器是该策略的隔离前提；修改网络模型后，应重新检查实际对端和策略匹配情况。

## IPv6 解析成功，但连接失败

AAAA 只表示域名声明了 IPv6 地址。服务器的公网 IPv6、Docker IPv6 网络、端口映射和两层防火墙都需实际可达。双栈部署分别检查 A 与 AAAA；旧的 AAAA 或错误 IPv6 路由可能导致部分客户端优先连接失败。

IPv6-only 中继要求客户端具备可用 IPv6 网络，并支持申请和使用 IPv6 relay 候选。仅支持 IPv4 的客户端无法直接使用；浏览器能通过 IPv6 打开网页，也不等于 WebRTC 已支持这条媒体路径。可先用双栈模式验证，再分别测试 IPv4 与 IPv6。

## TLS 连接失败

核对 `TURN_TLS_ENABLE=1`、证书有效期与域名、私钥匹配、容器读取权限，以及公网 TCP 端口。默认地址为：

```text
turns:relay.example.com:5349?transport=tcp
```

`turn:` 和 `turns:` 分别对应普通和 TLS 连接。证书更换后需重新部署，使新进程读取证书。

## 更新后账号变化或镜像找不到

原账号由 `.env` 与 `secrets/turn-password` 共同保存。恢复这两项后重新部署即可沿用原账号。`--no-build` 要求本机已有 `localaudio-ningq:local` 镜像；镜像缺失时，在解压后的发行包目录执行：

```sh
sha256sum -c LocalAudio-Server.tar.gz.sha256 &&
sudo docker load -i LocalAudio-Server.tar.gz &&
sudo docker image inspect localaudio-ningq:local &&
sudo sh scripts/deploy.sh --no-build
```
