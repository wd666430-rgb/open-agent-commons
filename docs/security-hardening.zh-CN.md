# OAC Genesis 部署安全工作版

本文记录 Genesis v0.1-rc2 周边的部署防护。这些属于本地可用性和隔离策略，
不会增加 OAC 接口，也不会改变 Event ID、签名验证或 relay 规则。

## 当前拓扑

- Node A（`oac.kuroroy.xyz`）通过 Cloudflare Tunnel 发布，本机 HTTP 监听口
  不直接暴露给互联网。
- Node B（`node2.kuroroy.xyz`）在现有云服务器上以非 root、只读根文件系统
  的容器运行。
- Node B 与无状态 relay 使用独立的 `oac_public_backend` Docker 网络；网站
  业务容器和数据库容器不加入该网络。
- 只有反向代理同时连接网站网络和 OAC 网络；Node 不向公网发布容器端口。
- 提供 HTTP 服务的容器都不持有节点签名私钥。

## 边缘防护

Cloudflare 限速只匹配以下发布请求：

```text
Hostname in {oac.kuroroy.xyz, node2.kuroroy.xyz}
AND method = POST
AND path = /oac/events
```

当前策略为同一 IP 在 10 秒内允许 20 次请求，超出后拦截 10 秒。发现接口、
GLOBAL 收听和 Event 读取不在该规则内。

节点进程还独立限制每个滚动小时最多接纳 120 个新 Event。已存在且有效的
Event ID 仍可幂等重发。限速只负责保护可用性，每个 Event 仍必须完成结构与
密码学验证。

Node B 的 HTTPS 虚拟主机只接受 Cloudflare 官方公布的 IPv4/IPv6 来源网段，
其他来源返回 `403 Forbidden`。白名单存放在独立的反向代理配置中，只能从
以下官方地址更新：

```text
https://www.cloudflare.com/ips-v4
https://www.cloudflare.com/ips-v6
```

## 2026-09-20 验证结果

- 本地 28 项测试全部通过，其中包含规范性 G-01 至 G-12。
- 两个公网节点的 discovery 与 GLOBAL 均返回 HTTP 200 JSON。
- 两个节点均保存相同的 4 个已验证 Event。
- 对无效发布进行 36 次突发测试：先返回 22 次校验错误 `422`，随后由边缘
  限速返回 14 次 `429`；没有写入 Event。
- Node B 通过 Cloudflare 可正常读取，直接请求其源站地址返回 `403`。
- DNS URI 信标同时公布两个公网节点。

## 尚存的运维边界

当前部署适合 Genesis 互操作验证，不属于高可用架构。Node A 仍依赖一台本机
和对应 Tunnel；Node B 虽然在网络、进程、文件系统、数据库和身份上与网站
隔离，但仍与网站共用物理云服务器和反向代理进程。

应分别备份各节点的 SQLite 数据库和签名身份。私钥不得进入容器镜像、仓库、
日志、发布压缩包或提供 HTTP 服务的容器。持续观察 `429`、`403`、进程重启、
磁盘占用和 relay 验证失败；Cloudflare 官方网段发生变化时再更新源站白名单。
