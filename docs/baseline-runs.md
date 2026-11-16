# AgentGuard 基线实验

核对日期为 2026-11-16。已完成的正式任务在 `/data1/yaoziao/agentguard` 串行运行，本地模型使用一张 GPU。

## 数据和统计口径

- **ATBench** 使用 `data/ATBench/test.json` 和 `splits/atbench-v1.json`。冻结划分为训练 600、校准 200、留出 200 条。留出集含 101 条安全和 99 条危险轨迹。原始数据版本为 `4476ef92ed8f85c8d58d8a5b9dfdf55aa7893138`。记录 F1、Recall、FPR、审核耗时和错误数。
- **AgentDojo** 使用 v1.2.2、`deepseek-v4-pro`、IPIGuard `c4a9209`、四个 suite 和 `important_instructions`。排除 `workspace:25` 后有 96 条正常任务和 935 条攻击任务。按 suite、任务 ID 和注入 ID 配对，记录 ASR、Utility、审核耗时和错误数。
- 审核耗时以秒计。AgentDojo 对最终保留样本中的成功审核调用取平均。Recovery FPR 待补动作级恢复金标。

## 启动参数与覆盖情况

在服务器设置 `run=/data1/yaoziao/agentguard/scripts/run-baseline.sh`。`dojo` 分别用 `benign` 和 `under_attack` 替换 `MODE`，默认覆盖全部四个 suite。使用空闲 GPU 的物理编号设置 `CUDA_VISIBLE_DEVICES`，API 对照组无需 GPU。

| 方法 | ATBench | AgentDojo | 启动参数 |
|---|---|---|---|
| AgentDoG 1.5 4B | 完整轨迹 200/200，逐步回放已验收 1 条 | 正常 96/96，攻击 935/935 | `--guard-model models/agentdog-4b --revision 3193b58d0c8924f5b5a79eb99cd31918e327024c --max-new-tokens 512`，CUDA、BF16、greedy。逐步回放用 `bash "$run" atbench-agentdog`，在线用 `bash "$run" dojo agentdog MODE`。 |
| 无护栏 `None` | — | 正常 96/96，攻击 935/935 | `bash "$run" dojo none MODE`。沿用任务代理、工具和注入配置。 |
| DeepSeek 直接判别 | 完整轨迹 200/200 | 在线对照为 `None` | `bash "$run" atbench-deepseek`。DashScope `deepseek-v4-pro`、temperature 0、关闭 thinking、512 tokens，逐条判别完整轨迹，复用 AgentDoG 的输入和判定格式。 |
| SafePred-prompt | 逐步回放 200/200 | 正常 96/96，攻击 935/935 | `bash "$run" atbench-safepred`、`bash "$run" dojo safepred MODE`。DashScope `deepseek-v4-pro`、temperature 0.3、关闭 thinking、2048 tokens、策略 `agentguard-safepred-v1`。 |
| TRACES | 末状态评分 200/200 | 正常 96/96，攻击 935/935 | 设置 `TRACES_RUN`，依次运行 `bash "$run" traces-train`、`bash "$run" atbench-traces`，在线用 `bash "$run" dojo traces MODE`。Qwen3-4B FP16 观察器 `1cfa9a7208912126459214e8b04321603b3df60c` 第 32 层，作者代码 `87579ab60ce6b13f38f7d1f531b6a906656f2748`，种子 42，两阶段各 30 epoch，机制数量 32。校准集选出的 F1 最优阈值为 0.195，AgentDojo 沿用同一检查点和阈值。 |
| ShieldAgent（ICML 2025）、DreamGuard | 待接入 | 待接入 | 待取得匹配论文的可运行实现或权重。 |

复现 AgentDoG 的完整轨迹组时，在服务器项目目录用 `.venv/bin/python -m agentguard atbench --method agentdog --data data/ATBench/test.json --split-manifest splits/atbench-v1.json`，附上表中的权重参数和新 `--output` 路径。

## 已完成正式结果

### ATBench

各组使用相同的 200 条留出轨迹，最终样本错误数均为 0。

| 方法 | 评分方式 | F1 ↑ | Recall ↑ | FPR ↓ | 平均审核耗时 ↓ |
|---|---|---:|---:|---:|---:|
| DeepSeek-v4-pro 直接判别 | 完整轨迹 | 48.72% | 38.38% | 18.81% | 9.780 秒 |
| AgentDoG 1.5 4B · 原适配 | 完整轨迹 | 64.76% | 68.69% | 42.57% | 8.299 秒 |
| AgentDoG 1.5 4B · 作者输入格式 | 完整轨迹，含工具说明 | 73.49% | 79.80% | 36.63% | 17.525 秒 |
| SafePred-prompt | 逐步回放，首次拦截判为危险 | 65.28% | 94.95% | 94.06% | 10.148 秒 |
| TRACES | 完整轨迹，按末状态评分 | 81.34% | 85.86% | 24.75% | 0.243 秒 |

耗时按每次成功审核计算。SafePred 有 337 次逐步审核，其余方法每条轨迹计一次评分。AgentDoG 结果为 `atbench-agentdog-4b-heldout-v1-20261110_115335.jsonl`。DeepSeek 结果为 `atbench-deepseek-20261112_160038.jsonl`，第 989 条的格式错误已按原参数补测成功，记录为 `atbench-retry-deepseek-989-20261113_124407.jsonl`。该次成功补测耗时 284.70 秒，计入平均值。

AgentDoG 论文表 2 报告同款 4B 的 F1 为 74.3%。上表 64.76% 对应 AgentGuard 的原输入模板。复跑使用 `--agentdog-author-prompt vendor/AgentDoG/prompts/v1.5/coarse_grained_moderation.txt`，采用作者公开的粗粒度提示及角色标记，将数据的 `tool_used` 映射为可用工具。模板来自作者仓库 `c8d803f267a43ec0e103a651265f50f1ff4456d5`。 [论文表 2](https://arxiv.org/html/2605.29801#S3.T2) · [作者推理示例](https://github.com/AI45Lab/AgentDoG/blob/c8d803f267a43ec0e103a651265f50f1ff4456d5/examples/getting_started_v1_5.md#coarse-grained-moderation)

512 token 试跑 `20261115_220939` 因判定格式错误提前结束。预留样本 1 在 512 token 被截断，到第 534 token 得到有效判定。预留样本 184 在 402 token 得到有效判定。正式复跑沿用同一 4B 权重、同一 200 条留出轨迹、BF16、贪心解码和关闭 thinking，输出上限改为 1,024 token。

复跑于 2026-11-15 23:13（北京时间）结束，结果为 `atbench-agentdog-author-heldout-1024-20261115_221521.jsonl`。TP/FP/TN/FN 为 79/37/64/20，200 条均有效。较原适配 F1 提升 8.73 个百分点，Recall 提升 11.11 个百分点，FPR 下降 5.94 个百分点。差异涵盖提示词、轨迹格式、工具信息和输出上限。论文表 2 是外部参考。

### AgentDojo

四组使用相同的 96 条正常任务和 935 条攻击任务，最终样本错误数均为 0。审核耗时为每次成功审核的平均值。

| 方法 | 正常 Utility ↑ | 攻击 ASR ↓ | 攻击 Utility ↑ | 平均审核耗时（正常 / 攻击）↓ |
|---|---:|---:|---:|---:|
| 无护栏 `None` | 86/96 · 89.58% | 56/935 · 5.99% | 806/935 · 86.20% | — |
| AgentDoG 1.5 4B | 63/96 · 65.63% | 7/935 · 0.75% | 677/935 · 72.41% | 9.099 / 9.356 秒 |
| SafePred-prompt | 73/96 · 76.04% | 3/935 · 0.32% | 813/935 · 86.95% | 33.156 / 10.671 秒 |
| TRACES | 46/96 · 47.92% | 18/935 · 1.93% | 431/935 · 46.10% | 0.207 / 0.237 秒 |

#### AgentDoG 分 suite

| AgentDoG · AgentDojo | 正常 Utility | 攻击 ASR | 攻击 Utility | 平均审核耗时（正常 / 攻击） |
|---|---:|---:|---:|---:|
| Workspace | 35/39 · 89.74% | 2/546 · 0.37% | 461/546 · 84.43% | 10.99 / 9.18 秒 |
| Slack | 9/21 · 42.86% | 1/105 · 0.95% | 46/105 · 43.81% | 8.33 / 11.10 秒 |
| Travel | 10/20 · 50.00% | 1/140 · 0.71% | 88/140 · 62.86% | 9.29 / 9.21 秒 |
| Banking | 9/16 · 56.25% | 3/144 · 2.08% | 82/144 · 56.94% | 7.81 / 8.18 秒 |
| 总体 | **63/96 · 65.63%** | **7/935 · 0.75%** | **677/935 · 72.41%** | **9.10 / 9.36 秒** |

原始 AgentDojo 批次为 `20261110_160001` 和 `20261111_170421`。Workspace 19/2、19/3 和 Banking 5/5 的三次判定格式错误均经补测成功，最终错误数为 0。原始文件保存在服务器的 `/data1/yaoziao/agentguard/results`。

AgentDojo `None` 批次为 `20261112_160038`。

#### SafePred-prompt 分 suite

批次 `20261113_142149`，AgentDojo 最后一组于 11 月 14 日 19:52（北京时间）结束。

| SafePred-prompt · AgentDojo | 正常 Utility | 攻击 ASR | 攻击 Utility | 平均审核耗时（正常 / 攻击） |
|---|---:|---:|---:|---:|
| Workspace | 32/39 · 82.05% | 2/546 · 0.37% | 509/546 · 93.22% | 96.84 / 10.28 秒 |
| Slack | 16/21 · 76.19% | 0/105 · 0.00% | 73/105 · 69.52% | 16.45 / 11.37 秒 |
| Travel | 14/20 · 70.00% | 1/140 · 0.71% | 117/140 · 83.57% | 9.83 / 9.57 秒 |
| Banking | 11/16 · 68.75% | 0/144 · 0.00% | 114/144 · 79.17% | 13.08 / 12.42 秒 |
| 总体 | **73/96 · 76.04%** | **3/935 · 0.32%** | **813/935 · 86.95%** | **33.16 / 10.67 秒** |

正常组有 522 次审核，中位 10.19 秒，其中 Workspace 有 41 次超过 60 秒。攻击组有 4,128 次审核，中位 8.08 秒。

#### TRACES 分 suite

批次 `20261114_214107`，AgentDojo 最后一组于 11 月 15 日 16:15（北京时间）结束。训练与校准参数保存在 `results/traces-atbench-20261114_214107/manifest.json`。

| TRACES · AgentDojo | 正常 Utility | 攻击 ASR | 攻击 Utility | 平均审核耗时（正常 / 攻击） |
|---|---:|---:|---:|---:|
| Workspace | 19/39 · 48.72% | 14/546 · 2.56% | 258/546 · 47.25% | 0.337 / 0.318 秒 |
| Slack | 9/21 · 42.86% | 4/105 · 3.81% | 24/105 · 22.86% | 0.108 / 0.133 秒 |
| Travel | 11/20 · 55.00% | 0/140 · 0.00% | 86/140 · 61.43% | 0.177 / 0.215 秒 |
| Banking | 7/16 · 43.75% | 0/144 · 0.00% | 63/144 · 43.75% | 0.107 / 0.131 秒 |

### 输入协议复核

| 已跑组 | 复核结论 |
|---|---|
| ATBench · DeepSeek 直接判别 | 与原 AgentDoG 使用相同的简化提示和历史序列，工具池为空。 |
| ATBench · SafePred-prompt | 逐步回放读取此前历史、当前候选动作和当时可见的观察，工具池为空。结果对应 DeepSeek-v4-pro 与固定策略的提示词适配。论文主表使用 Qwen3-Max 护栏，在 OS-Harm 和 WASP 评测。 [SafePred 论文](https://arxiv.org/html/2602.01725v1#S4) |
| ATBench · TRACES | 作者运行示例显式使用 `--no_tool_pool`。已核对 800 条训练及校准 ID 与 200 条留出 ID 的交集为 0。检查点的机制数为仓库默认的 32，论文附录 B.3 的配置为 8。我们的 F1 为 81.34%，论文 Qwen3-4B 同类骨干的 F1 为 84.5%。 [TRACES 论文](https://arxiv.org/html/2605.27690v2#S4.T1) · [论文附录 B.3](https://arxiv.org/html/2605.27690v2#A2.SS3) · [作者代码](https://github.com/lab-flair/TRACES#2-atbench-pipeline) |
| AgentDojo · 四组 | 使用同一任务代理、注入配置和任务 ID。AgentDoG、SafePred 在审核时收到可用工具 schema。TRACES 审核候选动作时从历史和动作提取表示，`None` 直接运行任务代理。 |

### ATBench 补跑配置

| 组别 | 划分 | 与已有结果的关系 |
|---|---|---|
| DeepSeek 直接判别，作者输入格式 | `splits/atbench-v1.json` | `--method deepseek --agentdog-author-prompt vendor/AgentDoG/prompts/v1.5/coarse_grained_moderation.txt --max-new-tokens 1024`。使用与 AgentDoG 73.49% F1 组相同的提示、轨迹、工具 schema 和输出上限。 |
| SafePred-prompt，含工具说明 | `splits/atbench-v1.json` | `--method safepred --include-tools`。将工具 schema 传入每步，沿用预测提示、策略版本、API 参数和首次拦截规则。 |
| TRACES，论文参数 | `splits/atbench-traces-seed42.json` | `traces_train --mechanisms 8 --threshold 0.3`。按作者公开的分层算法和 seed 42 重建划分，共 599 条训练、200 条验证、200 条留出。第 908 条仅有文本回复，按公开的动作提取命令排除。沿用公开 README 的固定阈值 0.3。原始作者逐条划分未在已固定的公开 checkout 中提供。 |
| TRACES，原划分配对 | `splits/atbench-v1.json` | `traces_train --mechanisms 8`。沿用原划分和验证集 F1 选阈值流程，对照已有的 K=32。 |

作者算法重建的测试 ID 与原固定测试 ID 相交 34 条。跨方法配对比较使用原划分。TRACES 末状态汇总同时记录 EDR 和 EAUPC，按论文 B.4 从各步风险分数计算。 [论文参数和指标](https://arxiv.org/html/2605.27690v2#A2.SS3) · [作者运行命令](https://github.com/lab-flair/TRACES#step-5-evaluate-atbench-model)
