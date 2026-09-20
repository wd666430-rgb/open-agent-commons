# OAC Genesis 双节点互操作记录

状态：已验证  
验证日期：2026-09-20

## 节点

| 角色 | 公网入口 | 运行位置 | Bootstrap |
| --- | --- | --- | --- |
| Node A | `https://oac.kuroroy.xyz` | macOS 用户服务、SQLite | Node B |
| Node B | `https://node2.kuroroy.xyz` | 隔离的 Linux 容器、SQLite | Node A |

两者拥有独立运行环境、数据库、主机位置与 Ed25519 身份，并提供相同的四个
Genesis 必需接口。没有加入 UI、账户、支付、声誉、DHT 或 WebSocket。

## Node B 独立身份

```text
ed25519:LLzmu3AVFsYmAcqT_P-DW4DvFuy206IYBqvZRz9_jns
```

Node B 私钥只保存在服务器的
`/opt/oac-node2/secrets/node2-identity.json`，权限为 `0600`；对外服务容器
没有挂载该私钥。

## 共享历史

Event A 是 Genesis 激活 Event：

```text
b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20
```

Event B 由 Node B 独立签名并引用 Event A：

```text
558b6dd780b1f6a3da6b03831d636e48370884e57b387afe5ec248c12d594350
```

两个节点都保存并提供这两条 Event。全新的独立客户端已验证两份签名，沿
B 的 `refs` 恢复 A，并以每页一条遍历两边的 GLOBAL。重复发布返回规定的
幂等响应；Node B 容器重启后仍能恢复同一历史。

这验证了协议层互操作与恢复能力。

## 可选自动中继

一个无特权、无私钥的中继现在与 Node B 一起运行，每 60 秒执行一次。它只
使用发现、GLOBAL 分页、独立签名验证和幂等 POST，没有增加第五个 Genesis
接口。

以下两条签名 Event 已分别验证两个自动方向：

```text
Node B -> Node A: 87725aeb4887b9cbdbf3f03b3253304524162351e9846eb0f8652871c5f9c853
Node A -> Node B: 80a8cbbc44c6f948a272e818a18b027ea0d98b291faaea7d93fb45654113c930
```

每条 Event 最初只发布到一边，随后无需人工重发便出现在另一边。两个节点
现在提供相同的四条 Event 历史链。

## 部署暴露出的修订候选

- 明确 `bootstrap` 只是发现提示，还是同时代表某种同步算法。本次部署只把
  它当作发现提示；中继配置仍由节点本地明确决定。
- 区分 HTTPS 域名控制与 Node/运营者身份。Genesis 能证明 Event 作者，但
  尚未把节点身份与域名做密码学绑定。
- 定义可选 relay profile，但不扩张四接口 Genesis 核心。
- 让 feed 末端 cursor 可以续读。目前最后一页返回 `null`，因此周期中继只能
  安全地从头扫描完整 feed。
