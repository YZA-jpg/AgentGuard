# AgentGuard 基线实验

核对日期为 2026-11-14。正式任务在 `/data1/yaoziao/agentguard` 串行运行，本地模型使用一张 GPU。

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
| SafePred-prompt | 逐步回放 200/200 | 正常 96/96，攻击组运行中 | `bash "$run" atbench-safepred`、`bash "$run" dojo safepred MODE`。DashScope `deepseek-v4-pro`、temperature 0.3、关闭 thinking、2048 tokens、策略 `agentguard-safepred-v1`。 |
| TRACES | Qwen3-4B 验收 2 条，正式训练待跑 | 攻击验收 1 条 | 设置 `TRACES_RUN`，依次运行 `bash "$run" traces-train`、`bash "$run" atbench-traces`，在线用 `bash "$run" dojo traces MODE`。观察器 `1cfa9a7208912126459214e8b04321603b3df60c` 第 32 层，作者代码 `87579ab60ce6b13f38f7d1f531b6a906656f2748`，种子 42，两阶段各 30 epoch，校准集选 F1 最优阈值。 |
| ShieldAgent（ICML 2025）、DreamGuard | 待接入 | 待接入 | 待取得匹配论文的可运行实现或权重。 |

复现 AgentDoG 的完整轨迹组时，在服务器项目目录用 `.venv/bin/python -m agentguard atbench --method agentdog --data data/ATBench/test.json --split-manifest splits/atbench-v1.json`，附上表中的权重参数和新 `--output` 路径。

## 已完成正式结果

两种 ATBench 完整轨迹判别方法的留出集 ID 完全匹配。

| ATBench · 完整轨迹 | 有效样本 | F1 ↑ | Recall ↑ | FPR ↓ | 平均审核耗时 ↓ |
|---|---:|---:|---:|---:|---:|
| AgentDoG 1.5 4B | 200/200 | 64.76% | 68.69% | 42.57% | 8.30 秒 |
| DeepSeek 直接判别 | 200/200 | 48.72% | 38.38% | 18.81% | 9.78 秒 |

AgentDoG 结果为 `atbench-agentdog-4b-heldout-v1-20261110_115335.jsonl`。DeepSeek 结果为 `atbench-deepseek-20261112_160038.jsonl`，第 989 条的格式错误已按原参数补测成功，记录为 `atbench-retry-deepseek-989-20261113_124407.jsonl`。该次成功补测耗时 284.70 秒，计入平均值。

| AgentDoG · AgentDojo | 正常 Utility | 攻击 ASR | 攻击 Utility | 平均审核耗时（正常 / 攻击） |
|---|---:|---:|---:|---:|
| Workspace | 35/39 · 89.74% | 2/546 · 0.37% | 461/546 · 84.43% | 10.99 / 9.18 秒 |
| Slack | 9/21 · 42.86% | 1/105 · 0.95% | 46/105 · 43.81% | 8.33 / 11.10 秒 |
| Travel | 10/20 · 50.00% | 1/140 · 0.71% | 88/140 · 62.86% | 9.29 / 9.21 秒 |
| Banking | 9/16 · 56.25% | 3/144 · 2.08% | 82/144 · 56.94% | 7.81 / 8.18 秒 |
| 总体 | **63/96 · 65.63%** | **7/935 · 0.75%** | **677/935 · 72.41%** | **9.10 / 9.36 秒** |

原始 AgentDojo 批次为 `20261110_160001` 和 `20261111_170421`。Workspace 19/2、19/3 和 Banking 5/5 的三次判定格式错误均经补测成功，最终错误数为 0。原始文件保存在服务器的 `/data1/yaoziao/agentguard/results`。

AgentDojo `None` 批次 `20261112_160038` 的 1,031 条任务与 AgentDoG 完全配对。正常 Utility 为 89.58%（86/96），攻击 ASR 为 5.99%（56/935），攻击 Utility 为 86.20%（806/935）。开启 AgentDoG 后，三项分别下降 23.96、5.24、13.80 个百分点，差值按未四舍五入的比例计算。

### SafePred-prompt

批次 `20261113_142149`。ATBench 逐步回放完成 200/200，F1 **65.28%**、Recall **94.95%**（94/99）、FPR **94.06%**（95/101），337 次审核平均 **10.15 秒**。完整轨迹结果采用不同的输入口径。

AgentDojo 正常组完成 96/96，Utility **76.04%**（73/96），522 次审核平均 **33.16 秒**。Workspace 有 41 次审核超过 60 秒。截至北京时间 11:26，攻击组为 685/935，Workspace 和 Slack 已完成，Travel 34/140，Banking 待启动。已有结果均无运行错误。

## 推荐顺序

1. 完成 SafePred-prompt 的 AgentDojo 攻击组，核对三种方法的任务配对与汇总。
2. 单卡串行完成 TRACES 训练、校准、ATBench 末状态评分和 AgentDojo 正常及攻击组。
3. 需要同协议的 ATBench 回放对照时，在同一留出集上补跑 `atbench-agentdog`。
