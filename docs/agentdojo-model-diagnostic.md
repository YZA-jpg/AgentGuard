# Flash / Pro 的 40 条配对诊断

用户于 2026-11-21 明确授权代为启动本次小规模诊断。其他后续测试仍遵循先给命令、由用户启动的默认约定。

| 组别 | 模型 | temperature 请求 |
|---|---|---|
| A_flash_t0 | deepseek-v4-flash-0731 | 显式 0 |
| B_pro_t0 | deepseek-v4-pro | 显式 0 |
| C_pro_default | deepseek-v4-pro | 完全省略 |

共同设置：官方 AgentDojo 0.1.35 / v1.2.2、作者依赖锁、原生无外接护栏流程、`important_instructions`、攻击称呼 `DeepSeek`、显式请求 `enable_thinking=true`、不设输出 token 上限、每组 4 个独立 API 进程。三组顺序运行，模型输入中的系统/初始用户提示、工具 schema 和注入字典已离线验证一致。B 对 A 比较当前服务下的模型差异，C 对 B 比较显式温度与省略温度的请求方式；服务实际默认温度未知，不能把省略当成某个已知数值。

固定样本来自 `deepseek_result` 的 939 条参考任务，在每个 suite 内按固定 ID 排序、seed 42 均匀抽取 10 条，不使用成功标签选样本。40 条的旧 Pro 记录恰有 23 条官方成功，仅为背景信息，不能与原 939 条总体 45.26% 直接比较。小样本是诊断集，不能充当论文正式全量成绩，也不能凭少数差异声称统计显著。

执行顺序：三组各跑一次相同的 Workspace `(0,0)` 接口验收，确认请求参数、实际响应模型与原生判分有效后，再跑 A/B/C 各 40 条；共 120 条诊断加 3 条单独保存的验收。每组结束自动独立复核。运行错误按既有有界策略记录和重试，不依据攻击是否成功重试。保留 15 轮原生工具预算及其终止情况。

本次输出目录：

`/data1/yaoziao/agentguard/results/agentdojo-model-diagnostic-20261121_005159`

重要文件：

- `experiment.json`：40 条 ID、参考文件哈希、三组配置、输入一致性签名、控制器与原生入口源码哈希。
- `probe_A_flash_t0` / `probe_B_pro_t0` / `probe_C_pro_default`：接口验收、原始请求响应和参数核查。
- `A_flash_t0` / `B_pro_t0` / `C_pro_default`：各组 `summary.json`、原生 trace、`cases.jsonl`、所有尝试及 API 请求响应。
- `comparison.json`：完成后的三组汇总、逐条配对结果、实际模型 ID、思考字段与 finish_reason 统计。Travel 目标 6 的字符串判分成功单列，仍需阅读内容确认是否只是拒绝时提及酒店名。
- 根目录 `batch.done` 和 `batch.exit=0`：三组运行及复核全部通过。

旧 Flash 949 条使用思考服务默认，本轮新 A 组显式开启，因此应使用这次 A/B/C 配对诊断来解释差异，不能直接把旧 Flash 总体分数当成本轮 A 组分数。底层模型快照及其他服务默认值仍可能影响结果，所有可见请求/响应均保留。

后台会话：

```bash
tmux -S /data1/yaoziao/agentguard/cache/tmux/model-diagnostic.sock attach -t model_diagnostic
tmux -S /data1/yaoziao/agentguard/cache/tmux/model-diagnostic.sock capture-pane -p -t model_diagnostic:run -S -20
```

启动验收后不由助手持续轮询结束；用户可自行查看或后续请求检查。当前批次无需重复启动。其他新批次可由用户使用 `bash scripts/run-model-diagnostic.sh 新目录`，相同代码/配置下恢复则追加 `--resume`。

离线验证记录：`/data1/yaoziao/agentguard/cache/audits/model-diagnostic-offline-tests-20261121.txt`，共 13 项通过；相同输入哈希预检通过。
