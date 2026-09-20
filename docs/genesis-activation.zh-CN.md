# OAC Genesis 激活记录

状态：已激活  
激活时间：2026-09-20T04:15:29Z

## 公开节点

```text
https://oac.kuroroy.xyz
```

Discovery：

```text
https://oac.kuroroy.xyz/.well-known/oac.json
```

Release：`genesis-0.1-rc1`  
Release hash：`ba66555febf2941384c57c0d59f30f1f1210e4e6e1c132bb276c79e96dbe65b8`

## Genesis 身份

```text
ed25519:rTIA28_TUyYPPWsf0XZo_IeofGKWBe8_ArcYwCbdbQ0
```

私钥种子不属于源码仓库或任何公开发布包。

## 第一个公共 Event

```text
id:   b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20
type: signal
time: 1789877729
text: OAC Genesis v0.1-rc1 exists. This Event anchors the first public OAC history.
```

直接读取：

```text
https://oac.kuroroy.xyz/oac/events/b488e83b9a27419556ed7c6df7d3310e90a4bd7905c18d5f2f85496cb2b29e20
```

首次发布返回 HTTP 201；幂等重发返回 HTTP 200；Node 进程重启后仍能恢复；
Reference Implementation 与独立 Client 均已完成签名验证。

## 第一次独立延续

位于 `https://node2.kuroroy.xyz` 的 Node B 独立验证了首条 Event，并签署了
一条引用它的第二条 Event：

```text
558b6dd780b1f6a3da6b03831d636e48370884e57b387afe5ec248c12d594350
```

两个公网 Node 现在都提供这两条 Event。验证记录见
`docs/node-interoperability.zh-CN.md`。
