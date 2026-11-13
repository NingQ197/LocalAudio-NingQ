LocalAudio Server 2.1.0，为 LocalAudio 屏幕共享提供可自行部署的 TURN 中继。

- 提供包含 Docker 镜像、配置和源码的离线包，支持本机下载后上传 Linux 服务器导入。
- 默认使用永久静态账号，入口为 21113 TCP / UDP。
- 支持 IPv4、双栈和 IPv6-only，提供可选 TURN TLS。
- 更新鉴权、网络策略和容器资源限制。

下载 `LocalAudio-Server.zip` 与 `SHA256SUMS.txt`。前者包含 **Linux amd64 镜像及完整部署文件**，后者用于校验 ZIP。GitHub 自动生成的 `Source code` 附件仅含源码。

[Linux 部署指南](https://github.com/NingQ197/LocalAudio-NingQ/blob/v2.1.0/docs/DEPLOYMENT.md)提供校验、解压、`docker load` 和启动命令，以及 IPv6、端口和 TLS 配置。
