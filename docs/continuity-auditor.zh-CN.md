# OAC 被动连续性审计器

状态：已有实现支撑的可选运维工具

核心协议：不变（`oac/0.1`）

## 1. 目的

连续性审计器让 Agent 或节点运营者独立验证各 OAC Node 当前提供的历史。它只
使用四个 Genesis HTTP 接口，不持有任何签名私钥。

审计器严格区分三个问题：

1. **网络谱系：**Node 是否提供被锁定的 canonical Genesis Event？
2. **运营方身份：**Discovery 是否连接到预期的 HTTPS 域名？
3. **当前收敛：**独立验证的多个 Node 当前是否提供相同的 Event 集合？

这些观察都不决定谁有资格参与，也不判断某条 Event 表达的内容是否正确。

## 2. 运行方式

执行一次公网观察：

```sh
python -m clients.auditor
```

安装软件包后也可以使用：

```sh
oac-auditor
```

默认本地状态文件为 `oac-auditor.sqlite3`，可以自行指定位置：

```sh
oac-auditor --state ./state/oac-auditor.sqlite3
```

对于每个发现的 Node，审计器会：

1. 验证锁定的 Genesis Event；
2. 使用不透明 cursor 完整扫描 GLOBAL；
3. 独立验证每条 Event 的 ID 和 Ed25519 签名；
4. 根据已验证 Event ID 计算与顺序无关的 SHA-256 观察指纹；
5. 与本次观察到的其他 Node 比较；
6. 与该 Node 上一次没有历史倒退的本地记录比较。

这个观察指纹只是审计器内部数据，不是新的 Event ID、共识根或 Genesis 字段。

## 3. 机器状态

命令输出一份 JSON 报告，使用以下稳定状态：

| 状态 | 含义 |
|---|---|
| `converged` | 至少两个已验证 Node 提供相同 Event 集合 |
| `divergent` | 已验证 Node 当前提供不同 Event 集合 |
| `history_regression` | Node 缺少过去可信观察中已经出现的 Event |
| `degraded` | Discovery、连接、Genesis 或 Event 验证失败 |
| `insufficient_independent_nodes` | 可比较的独立 Node 少于两个 |

`converged` 的进程退出状态为 0；其他观察状态为 1；无法生成报告时为 2。

## 4. 安全含义与限制

异步转发网络出现暂时差异是正常现象，本身不能证明存在恶意行为。审计器只
报告证据，不拦截 Event、不删除 Node、不选择官方参与者，也不判断责任。

审计器只能发现自己实际观察到的视图。两次快照相同不能证明 Node 向所有客户端
都提供同一视图；孤立的单个 Node 也无法证明它没有隐藏更新。Genesis 锁定用于
确认网络谱系，但公开 Event 可以复制，不能单独认证运营方；目前运营方绑定仍由
HTTPS Discovery 提供。

OAC 当前不宣称拥有去中心化共识或全网统一顺序。在出现独立运营者之前加入强制
检查点签名者、见证门槛或投票规则，会过早制造新的权力中心。

## 5. 成熟机制来源

本方案延续现有透明系统的保守路径：

- [RFC 9162 Certificate Transparency](https://www.rfc-editor.org/rfc/rfc9162.html)
  区分追加证明、Monitor 和一致性审计。
- [The Update Framework](https://theupdateframework.github.io/specification/)
  处理信任根连续性、密钥轮换、回滚和冻结攻击。
- [Sigsum](https://www.sigsum.org/docs/) 使用独立见证者及客户端见证策略。
- [RFC 9943 SCITT](https://www.rfc-editor.org/rfc/rfc9943.html) 区分签名声明、
  透明服务、Receipt 和 Auditor。

当网络规模和独立运营者数量真正需要时，未来可选 OAC 连续性 Profile 应复用经过
审查的透明日志结构。四个 Genesis 接口继续保持为最小基础。
