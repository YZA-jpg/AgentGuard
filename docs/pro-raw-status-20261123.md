# Pro原始JSON组结果与下一步

**收尾更新（11月23日20:00）：38条429已全部补齐，最终200/200、零错误，F1=59.02%、Recall=54.55%、FPR=29.70%、Latency=3.1671秒。原162条成功输出保持不变；新结果位于`atbench-pro-raw-retry-20261123_134212/merged`，完成时间13:46:26。SafePred也已于13:54:32核验完成1046条。以下13:25内容保留为历史记录，不需要再次执行其中38条补测命令。最新总结与计划见[近一周简报](weekly-summary-20261123.md)。**

核对时间：2026-11-23 13:25:55（北京时间）。本次只做结果检查、CPU复核和补测入口准备，未自动启动新的正式API测试。

## 当前结果

`results/atbench-pro-raw-20261123_123758`已结束，`batch.exit=1`、没有`batch.done`。200条均已尝试，162有效、38个HTTP429 RateLimitError；不是格式解析失败。38条恰好均为安全标签，所以当前有效范围为99危险＋63安全，少了38条安全结果。

只看有效162条：TP54、FP9、TN54、FN45；F1=66.67%、Recall=54.55%、FPR=14.29%、平均审核2.9210秒。输入669,546、输出8,429 tokens均来自已返回的API用量；响应模型162次均为deepseek-v4-pro，未命中输出上限，没有本地输入截断。输出核验状态`complete_with_errors_verified`只表示已存结果可重算，不表示200条都成功。

为避免与完整200分母混用，另从旧作者模板组提取**完全相同162条**：

| Pro配置，同162条 | TP/FP/TN/FN | F1 ↑ | Recall ↑ | FPR ↓ | Latency（秒/审核）↓ |
| --- | --- | ---: | ---: | ---: | ---: |
| AgentDoG作者模板 | 74/13/50/25 | 79.57% | 74.75% | 20.63% | 16.3176 |
| 通用提示＋原始JSON | 54/9/54/45 | 66.67% | 54.55% | 14.29% | 2.9210 |

在这批相同记录上，新组少检出20条危险轨迹，也少了4条安全误报；提示、序列化与输出格式同时改变，不把差异归因于提示这一项。这里的作者模板79.57%是162子集，完整200的70.81%仍保留，二者不能混称。

原正式200中99条危险均已有输出，因此只补这38条安全样本时Recall仍为54.55%；最终F1/FPR应等补齐后再报告。对目前固定162条，若38条补测有k条误报，最终F1=108/(162+k)、FPR=(9+k)/101；不能将当前9/63的14.29%直接当作200条的误报率。

原文件：`/data1/yaoziao/agentguard/results/atbench-pro-raw-20261123_123758/formal`；结果SHA256=`4cccc3b4eefbe49731d9f3bb733c29a51a395a2e85da9e823f7f5607f9acd589`。

## 先补38条429

现有记录未保存底层provider code，暂不能区分RPM/TPM/额度类限制。[百炼错误码说明](https://help.aliyun.com/zh/model-studio/error-code)将429归为速率或额度限制，建议按具体code降并发/请求或token速率，明确额度耗尽则先处理额度。

补测入口保留162条成功记录，校验原文件哈希、提示、数据、划分和输入，再只调用原429失败项。不改模型、temperature0、thinking关闭和1024输出预算。新结果另存，不覆盖旧组。

- 单线程；不同样本间间隔3秒，不依赖GPU。
- 最多5次额外429重试，10/20/40/60/60秒退避，尊重Retry-After；总等待预算300秒。明确insufficient_quota等额度错误不反复重试。
- 一条经完整退避仍429时停止这一批，保留尚未处理的原错误，不连续撞剩余请求。日志记录provider code/request ID，不输出密钥或完整异常正文。
- 保存每次尝试、checkpoint、来源哈希和独立重算。补测后的延迟为原失败耗时＋新请求/退避，排除离线暂停与样本之间节流。原162条是4路执行，补测38条是1路，明确为混合执行口径。

服务器启动：

```bash
cd /data1/yaoziao/agentguard
mkdir -p cache/tmux
tmux -S "$PWD/cache/tmux/atbench-pro-raw-retry.sock" new-session -d -s pro_raw_retry \
  'cd /data1/yaoziao/agentguard && AGENTGUARD_SOURCE_COMMIT=a8dd3cd bash scripts/retry-atbench-pro-raw.sh results/atbench-pro-raw-20261123_123758/formal'
```

查看：

```bash
tmux -S /data1/yaoziao/agentguard/cache/tmux/atbench-pro-raw-retry.sock attach -t pro_raw_retry
```

结果在`results/atbench-pro-raw-retry-时间戳/merged`，包括`summary.json`、`verification.json`、`progress.json`、`provenance.json`和`retry-attempts.jsonl`。`cache/atbench-pro-raw-retry-active.json`记录当前路径。成功才写上级`batch.done`。若还有错误，继续保留并报告，不把错误计为安全。

## 后续顺序与验收

| 优先级 | 工作 | 当前状态 / 完成条件 |
| --- | --- | --- |
| P0 | 补齐Pro原始JSON组 | 新入口准备完成，用户启动；原162不变，200有效、零错误、输入/输出/指标核验通过后入主表 |
| P0 | SafePred AgentDojo收尾 | 正在运行1038/1046、剩8条；不重启；1046有效并通过作者响应重放核验后，CPU更新五护栏共同样本F1表 |
| P1 | 冻结本轮数据表 | ATBench统一200、全量1000/其他划分分开；SafetyDrift72五护栏齐全；AgentDojo在线基线、回放分类、错误覆盖率分开 |
| P1 | 原生在线AgentDojo接口验收 | 先用较快的ShieldAgent-THU做固定8条小样本，保持同一Pro/攻击/套件与冻结判别设置；测真实ASR/Utility和审核延迟，再决定全量。明确为运行时迁移适配 |
| P2 | DreamGuard迁移诊断 | 保留当前方法复现身份和全拦截结果，先核对输入/状态/源校准；不拿ATBench或AgentDojo测试标签调阈值追逐论文分数 |

SafePred结束后使用[现成CPU重算命令](agentdojo-replay-classification-20261123.md#结果和重算命令)，不需要重跑已完成护栏。AgentDoG的1条解析错误继续报告，四组/五组比较统一排除同一无效ID；若有新增错误则共同子集相应明确更新。

先收尾再扩规模。TRACES在ATBench开发数据上训练，不能把训练记录纳入1000条全量后与零样本模型混排成独立测试。新的在线全量或新攻击策略待该阶段配置确定后另给启动命令，本次不自动启动。
