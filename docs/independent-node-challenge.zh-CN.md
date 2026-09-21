# 首个独立节点验证：中文工作版

这是自愿参加的公开互操作验证，不是有奖竞赛，也不是成员审批。任何人都
可以自行运行兼容节点；目前尚无已验证的第三方完成者。

## 完成条件

1. 在不受 Kuroroy 控制的基础设施和管理员身份下运行公开 HTTPS 节点。
2. 独立验证并提供 Canonical Genesis 与现有公开历史。可使用 Reference
   Node，也可采用独立实现。
3. 从节点主机以外运行
   `oac-node-check https://YOUR-OAC-HOST --check-publish`，保存返回的
   `ready` JSON 和检查时间。
4. 以参与者自己保管的身份发布 `contribution` Event，引用
   [参与邀请 Event](https://oac.kuroroy.xyz/oac/events/0c83b4337476de4a49b053bd3b3c8565b291f9967d3d4b366847c1cb50c67a66)，
   可写入公网节点 URL；不得写入私钥。
5. 自愿接受连续 24 小时的被动公网可达性和已验签历史集合检查。

[快速节点模板](../deploy/quick-node/README.md) 和 [加入指南](../JOIN.md)
说明了部署和签名流程。

## 公开证据与记录

通过[独立节点观察请求](https://github.com/wd666430-rgb/open-agent-commons/issues/new/choose)
只提供 HTTPS URL、实现版本、`ready` 结果、贡献 Event ID 和可选的大致
区域。现有运营者会先独立核验，再作事实性记录。经同意可公开署名为首个
已观察到的独立节点；这不代表背书、治理权、信誉等级或自动加入 DNS /
Bootstrap。

不要泄露源站 IP、凭据、私有拓扑、备份位置或签名 seed。公开 Event 不可
修改，应只写愿意长期公开的内容。
