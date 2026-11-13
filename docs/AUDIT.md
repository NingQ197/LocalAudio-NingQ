# 安全机制与验证

[返回首页](../README.md) · [安全说明](../SECURITY.md)

## 鉴权和观看权限

TURN Allocate 强制长期鉴权，默认使用永久静态账号。首次 401 是认证挑战；客户端随后携带用户名、realm、nonce 与消息完整性信息重试。普通 STUN Binding 不需要账号。

中继账号控制带宽与配额。共享观看身份、频道和会话由 LocalAudio 插件处理，并受 TS 频道访问规则约束。WebRTC 媒体使用 DTLS-SRTP；TURN 可以获知连接地址和流量元数据。

## 网络与资源

- 校验地址、端口、鉴权参数和 TLS 文件，拒绝匿名模式、任意 coturn 附加参数及换行注入。
- relay 地址必须是容器实际网卡地址；IPv4、双栈、IPv6-only 分别使用对应监听和地址映射。
- 对端策略限制私网、回环、链路本地、云 metadata 和特殊用途地址。仅对实际选中的本容器 relay 地址保留精确例外，支持同服务 allocation 互通。
- TCP 可作为客户端到 TURN 的传输；RFC6062 TCP 对端中继关闭。
- coturn 设置账号与全服务配额、带宽限制、分配和握手超时。
- 容器使用非 root UID `65534`、只读根目录和临时内存目录，删除 capabilities，禁止获得新权限；Compose 限制内存、CPU、PID、文件描述符和日志容量。
- 不启用 CLI、Web 管理、RFC5780、DTLS 监听、mobility 或 metrics 接口。

relay 地址例外按 IP 生效，默认 bridge 与单用途容器构成隔离前提。IPv6 不会取消鉴权或扩大其他私网地址的访问范围。

## 镜像和依赖

镜像基于校验 SHA256 的 coturn 4.18.0 源码，构建时应用局部补丁 [coturn-own-ula.patch](../server/coturn-own-ula.patch)。上游会在普通对端规则之前拒绝 ULA；补丁仅允许与服务实际选定 relay 地址完全相同的 IPv6 ULA 继续进入原有白名单、黑名单判定，用于同容器 allocation 互通。入口脚本先核对该 relay 地址确实属于容器网卡。其他 ULA、链路本地等内部目标仍受限制。

运行镜像采用多阶段构建，保留入口、OpenSSL 和 libevent 等必要组件，不包含数据库后端客户端、编译器或构建工具。基础系统继承的 SQLite 依赖链同时移除，删除集合与入口必需命令在构建中核对。上游许可证与本地修改说明见[第三方声明](../server/THIRD_PARTY_NOTICES.txt)。

Debian 基础镜像固定摘要，构建时安装当前安全更新。重建日期不同，系统包版本可能不同。上游信息见 [coturn 安全公告](https://github.com/coturn/coturn/security/advisories)。

## 自动检查范围

仓库工作流包含：

1. 源码发布边界与 Shell 语法检查。
2. 配置校验、永久账号、密码文件、TLS 证书和密钥、部署模式及发布扫描负例测试。
3. Compose 配置检查与实际 Docker 构建。
4. 真实容器 UDP / TCP / TLS 鉴权，匿名、未知用户和错误密码拒绝，兼容 shared-secret 模式，以及受限对端测试。
5. 两个实际 TURN allocation 的双向 UDP 载荷转发与释放。
6. 容器权限、资源限制、日志、引擎版本和运行依赖检查。
7. 最终镜像依赖扫描与离线发行包完整性校验。

漏洞扫描报告保留在 Actions 附件中。当前发行版提供修复版本的 HIGH / CRITICAL 条目会阻止检查通过；其他条目继续列入报告，其影响需结合上游补丁和实际组件判断。扫描覆盖当时数据库可识别的依赖问题。

## 实际部署验证

本地协议测试不覆盖特定云安全组、NAT、运营商路由或用户客户端。部署后使用两端插件客户端强制 TURN，确认实际选中 `relay`，检查视频、共享音轨、多观众和断线恢复。双栈与 IPv6-only 还需分别验证公网地址族和客户端支持。
