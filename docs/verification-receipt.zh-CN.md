# 可选验证回执

OAC 验证回执是一份机器可读的 Event 检查记录。它属于应用层约定，不是第
五个 Genesis 接口、新的 Event 类型，也不能证明 Event 中的陈述为真。

无第三方依赖的 Node.js 客户端可以直接从公网节点生成回执：

```sh
node clients/oac_js.mjs receipt https://oac.kuroroy.xyz EVENT_ID
```

也可以检查一份离线副本而不发布：

```sh
node clients/oac_js.mjs receipt event.json --source offline-copy
```

输出包含目标与实际 Event ID、来源、观察时间、客户端及版本，并分别记录远
程读取、内容派生 ID 和 Ed25519 签名的结果。无法执行的检查明确标为
`not-tested`；失败的回执在打印 JSON 后以状态码 2 退出。

如需形成公开可归属记录，获得授权的作者可以把回执 JSON 或简短摘要放入一
条已签名 `result` Event 的 `text`，并在 `refs` 中引用被验证 Event。回执不
得包含私钥。签名只能证明作者签署了这份陈述，其他观察者仍应独立复核。

互操作测试应由两个独立运行环境从不同节点检查同一条真实 Event，再比较回
执。可以使用离线篡改副本作为反例，但绝不能把它作为真实 Event 发布。
