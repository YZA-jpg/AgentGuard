# ATBench 最新正式结果

核对日期：2026-11-19。已逐条核对正式文件的测试 ID、原始标签、混淆矩阵和 F1/Recall/FPR；以下各组均完整完成、错误数为 0。原始结果位于服务器 `/data1/yaoziao/agentguard/results`。本地机器可读汇总为 `results/atbench-latest-summary-20261119.json`。

**复现状态更新：完成运行不等于通过原论文复现验收。** 当前 SafePred-prompt 为手写适配、TRACES K=32 为非论文配置，均不纳入论文配置的复现主比较；AgentDoG 的 200 条结果也不是论文全量 ATBench 分数。ShieldAgent 是 THU 官方模型的 ATBench 迁移评测。以下保留历史运行数据，不构成严格复现排名。逐项差异与修正计划见 [论文一致性核对](plans/2026-11-19-paper-faithful-baselines.md)。

2026-11-20：SafePred 作者核心已接入并通过原生提示/解析/评分/决策一致性测试，新的 Qwen3-8B 组已启动 ATBench 200 条、随后 SafetyDrift 72 条串行重测。新入口为 `agentguard.safepred_author_eval`，使用冻结的作者流程提取政策，不再使用下表的手写 SafePred-prompt。新结果尚在运行，不以校准 smoke 分数替代正式结果；完整参数见 [本轮协议](plans/2026-11-20-safepred-author-retest.md)。

## 固定配对 200 条：已运行记录

统一使用 `splits/atbench-v1.json`：99 条危险、101 条安全。此表记录已运行的模型对照与方法适配。DreamGuard 方法尚待完善与验收，暂不纳入有效比较。TRACES 的不同划分见下一表。正类为危险轨迹。

| 方法 / 配置 | 评分方式 | TP/FP/TN/FN | F1 ↑ | Recall ↑ | FPR ↓ | Latency ↓（秒/次） |
|---|---|---|---:|---:|---:|---:|
| DeepSeek-v4-pro，通用判别基线（AgentDoG 作者模板） | 完整轨迹，直接二分类 | 74/36/65/25 | 70.81% | 74.75% | 35.64% | 15.925 |
| AgentDoG 1.5 4B，作者输入格式 | 完整轨迹 | 79/37/64/20 | 73.49% | 79.80% | 36.63% | 17.525 |
| ShieldAgent-THU，官方检查点、原生 32k | 完整轨迹 | 80/59/42/19 | 67.23% | 80.81% | 58.42% | 0.403 |
| SafePred-prompt，历史手写适配，待官方核心重做 | 逐步回放，首次拦截判危险 | 96/95/6/3 | 66.21% | 96.97% | 94.06% | 10.933 |
| TRACES，K=32、阈值 0.195，历史非论文配置 | 完整轨迹，末状态评分 | 85/25/76/14 | 81.34% | 85.86% | 24.75% | 0.243 |

参数说明：DeepSeek 和 AgentDoG 使用同一 AgentDoG 作者 coarse 模板和工具 schema，输出上限 1024；DeepSeek temperature=0、thinking 关闭，AgentDoG BF16、greedy。SafePred 使用 DeepSeek-v4-pro、temperature=0.3、2048 tokens、固定策略，349 次审核。ShieldAgent 使用官方 THU Qwen2.5-7B 判别权重和作者 scorer，FP16、SDPA、batch 1、greedy、10 tokens；该子集有 3 条输入按原生窗口截断。TRACES 此行保留现有同一测试集的 K=32 结果，不代表最新 K=8 配置。

延迟为各自每次审核的平均值；完整轨迹一次审核与逐步回放一次审核的输入和调用数不同。

## TRACES 两种协议

| TRACES 配置 | 测试范围 | TP/FP/TN/FN | F1 ↑ | Recall ↑ | FPR ↓ | Latency ↓（秒/次） |
|---|---|---|---:|---:|---:|---:|
| K=8，阈值 0.3，最新论文参数组 | 作者公开算法重建的另一组 200 条 | 89/33/68/10 | 80.54% | 89.90% | 32.67% | 0.241 |
| K=32，校准阈值 0.195，既有配对组 | 与上表相同的固定 200 条 | 85/25/76/14 | 81.34% | 85.86% | 24.75% | 0.243 |

两组均采用作者 Stage-A/Stage-B 代码、Qwen3-4B 第 32 层、seed 42、两阶段各 30 epoch，按末状态评分。最新 K=8 组使用 `splits/atbench-traces-seed42.json`，599 训练/200 校准/200 测试，按作者动作提取流程排除无工具动作的 908；与原固定测试集只重叠 34 条。因此两行不是单独改变 K 的受控消融，**80.54% 不能直接参与上表的配对排名**。K=8 的原固定划分配对重训尚无已完成正式结果。K=8 组另有 EDR=63.64%、EAUPC=0.78793。

## ShieldAgent 全量与长上下文补充

| 配置 / 范围 | 样本数 | TP/FP/TN/FN | F1 ↑ | Recall ↑ | FPR ↓ | Latency ↓（秒/次） | 截断数 |
|---|---:|---|---:|---:|---:|---:|---:|
| 原生 32k，全量 ATBench | 1,000 | 420/260/243/77 | 71.37% | 84.51% | 51.69% | 0.450 | 25 |
| 原生 32k，同一超长子集 | 25 | 24/0/0/1 | 97.96% | 96.00% | — | 3.627 | 25 |
| YaRN 128k，独立扩展对照 | 25 | 23/0/0/2 | 95.83% | 92.00% | — | 19.428 | 4 |

25 条均为危险轨迹，无法估计 FPR；原生 25 条是全量结果的子集，YaRN 预测没有替换主表。全量 1,000 条与固定 200 条样本组成不同，勿混用排名。ATBench 缺少独立 recovery 标签，本次各组 recovery FPR 均留空。

## 判别基线命名与暂不纳入项目

“直接判别”指任务：让模型根据现有轨迹输出安全/危险；“作者输入格式”指提示模板与轨迹序列化方式。二者可以同时成立。本表的 DeepSeek 行就是使用 **AgentDoG 作者模板的通用模型直接判别基线**，不是 DeepSeek 作者发布的 ATBench 专用配置，也没有训练专用护栏或增加世界模型。

旧简化输入（JSON 轨迹、工具池为空、512 输出 tokens）与新作者模板（角色标记、工具 schema、1024 输出 tokens）在同一 200 条上的 Pro 结果分别为 F1 48.72% / 70.81%、Recall 38.38% / 74.75%、FPR 18.81% / 35.64%。因此新组 F1/Recall 更高，但 Pro 误报也更多；差异同时包含提示、信息量和输出上限，不能归因于序列化格式这一项。正式 Pro 对照保留新组，旧组作为历史输入适配实验。各专用护栏保留其自身作者提示/推理流程，并不统一改用 AgentDoG 模板。ATBench 此项不运行任务代理；未找到已完成的 ATBench Flash-0731 正式组。

DreamGuard 是独立方法复现，无作者 checkpoint，目前实现与验证尚未验收，**暂不计入主表、有效护栏比较或排名**。已有迁移试验仅保留为开发记录，原记录和参数见 `baseline-runs.md` 的历史批次。

## 结果索引

均相对于服务器 `/data1/yaoziao/agentguard/results`：

| 方法 | 正式文件 |
|---|---|
| DeepSeek 通用判别基线（AgentDoG 作者模板） | `atbench-deepseek-author-20261116_091817_909064276.jsonl` |
| AgentDoG | `atbench-agentdog-author-heldout-1024-20261115_221521.jsonl` |
| SafePred-prompt | `atbench-safepred-tools-20261116_091817_917392823.jsonl` |
| TRACES K=8 | `atbench-traces-20261116_091817-paper-k8.jsonl` |
| TRACES K=32 | `atbench-traces-20261114_214107.jsonl` |
| DreamGuard 方法复现版（开发记录，暂不计入） | `dreamguard-atbench-method-20261118_154154/atbench.jsonl` |
| ShieldAgent | `atbench-shieldagent-thu-20261119_010945/{formal,yarn-long25}/atbench.jsonl` |

本次服务器写新汇总时返回磁盘空间不足，故统一汇总先保存在本地并备份文档到 GitHub；服务器原始实验记录未改动。
