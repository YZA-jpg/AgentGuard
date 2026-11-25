# SafetyDrift 复核（2026-11-25）

最终任务为固定测试集72条上的逐动作、执行前审核。首次 HOLD/BLOCK 计轨迹阳性。分类报告 F1、Recall、FPR，时序另列 PHIR、MAS，端到端延迟单位为秒/审核。论文未提供已核实的同一份清理后 ID 清单。本文的百分点差异是跨报告的描述性差异。

| 方法 | 本地 F1 / Recall / FPR | DreamGuard 表1 F1 / SR / FPR | 本地秒/次 |
|---|---|---|---:|
| SafePred，原始 Qwen3-8B、政策 v2 | 8.89 / 5.26 / 14.71 | 45.3 / 37.0 / 44.4 | 17.968 |
| TRACES，SafetyDrift 内训练 | 96.00 / 94.74 / 2.94 | 87.1 / 96.3 / 33.3 | 0.0808 |
| DreamGuard v2，独立训练 | 97.44 / 100 / 5.88 | 96.4 / 96.3 / 3.7 | 0.0723 |

SafePred 官方合并权重已落在 data1 的 models/safepred-8b-author。版本 430a412fa7d055fa5c8348e73d9fe20ac251949a。入口 agentguard.safepred_distilled 对照冻结 v2 政策和原状态映射，固定 temperature 0.3、历史7、单候选、最大4000输出、关闭 thinking。45.3 来自 DreamGuard 的基线实验，论文未逐项给出其 SafePred 推理配置。正式命令在服务器项目根目录执行：

```bash
tmux new-session -d -s safepred8b_sd72 'cd /data1/yaoziao/agentguard && env -u LD_LIBRARY_PATH CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=2 .venv/bin/python -u -m agentguard.safepred_distilled --out-dir results/safepred8b-sd72-$(date +%Y%m%d_%H%M%S)'
```

DreamGuard 对照沿用冻结权重、校准57和测试72。固定种子20260701，分别按 argmax 或分类采样推断潜状态，再用对应推断模式在源校准集确定阈值。两者都是 TP38/FP2/TN32/FN0、PHIR 94.74%，MAS 从3.36变为3.64。论文 PHIR 96.3%、MAS 3.63。此次只比较分类与时间步，缓存特征计时不进入主表。ATBench 固定开发集6安全＋6危险，两种推断仍然全部干预。该改动未达到跨域修复目的，保留原主表。结果在 results/dreamguard-latent-paired-20261125。此前目标域单独校准后 heldout200 的 FPR 8.91%、Recall 6.06%，提示特征区分能力有问题。下一步在开发域比较相同任务、相同动作而历史不同的配对，并核对与作者的序列化和校准配置。

TRACES 复用作者两个阶段，K=8、原观察器第32层，使用校准集最大前缀风险选阈值0.8。当前TP36/FP1/TN33/FN2，Recall略低于论文，FPR低30.36个百分点。原评测实现采用自己的SafetyDrift适配。37个测试场景都在训练集出现，35条测试轨迹有训练中相同早期事件前缀。场景多数规则得到97.30% F1。因此需要同场景异标签配对和逐ID论文split核对。详见 [训练资产审计](safepred-policy-v2-traces-audit-20261124.md)。

[DreamGuard 原文与附录](https://arxiv.org/html/2608.05695v1) · [SafePred 作者权重](https://huggingface.co/yurun-chen/SafePred-8B)


跨域开发误拦定位：两个潜状态模式的6条安全轨迹均为首步工具 BLOCK 3条、首步文本回复 BLOCK 1条、后续工具 HOLD 2条。即时风险和累计风险两条路径都参与了误报。ATBench 开发集候选中的文本回复为296/875，SafetyDrift 校准集为54/484。该输入差异单独不能解释误报。TRACES 原始日志的 PHIR 为94.74%，MAS 为2.78，论文表2为87.1%和2.00。

新增 ATBench 开发诊断：200 个不同任务，无同任务天然配对。固定哈希选 40 条估计无标签均值偏移，另 40 条评估。冻结原源域阈值和权重，全字段对齐后 FP 从22降至21、TP仍18；不足以采用。首步受控替换动作改变26/40个判决，替换任务改变6/40个判决。原始分数见服务器 results/dreamguard-alignment-dev-20261125。

### DreamGuard 动作格式与跨域排序复核

服务器目录 `results/dreamguard-terminal-dev-20261125`。固定 v2 权重和 SafetyDrift 源阈值，在 ATBench 开发集200条上比较原始动作与终止回复解包。解包仅接受完整的 Complete 对象、唯一 response 字段和字符串正文。296 次回复、195 条轨迹的实际编码输入发生变化。两组均 TP99、FP101、TN0、FN0。

冻结源域融合权重，按 ID 哈希将 ATBench 开发集分为100条拟合和100条验证，仅用拟合侧安全轨迹的全程最大值计算目标域阈值。统一阈值和按工具/回复分别校准均 TP0、FP1、TN49、FN50。验证集原始即时/融合最大风险的 AUROC 为0.4448/0.4468，解包后为0.4188/0.4440。不能靠解包或升高阈值恢复检测能力，保留原正式方法。

SafetyDrift 训练与校准、ATBench 校准之间同名调用仅 send_email/send_message；SafetyDrift 校准的安全轨迹中二者均无样本，无法进行同名同参数良性调用的跨域风险比较。下一步应在源域训练数据构造同工具且标签不同的配对，验证对参数及前缀的区分，再决定是否改风险监督。未使用正式测试数据选择本轮参数。

### SafetyDrift 监督覆盖修正

实际训练前缀中所有工具仅出现单一即时标签，工具名与危险标签完全绑定。训练正例工具为 http_request、send_email、send_http_request、send_message。仅从训练集取这四个名字，在冻结72条上执行工具名规则，得到 TP38/FP0/TN34/FN0、F1=100%、PHIR=0%。该结果说明轨迹分类可被工具名规则完全解释，规则在危险动作处触发，无法提前预警。

因此此前提出的源域天然同工具异标签配对无法实施。DreamGuard 97.44%和TRACES96%的同源轨迹分类分数受该覆盖限制。高F1不能单独验证后果预测能力。代码 dreamguard_data.supervision_coverage 现在将实际监督前缀中的每工具正负样本数写入数据准备清单，可提前发现缺少反例的问题。当前公开标签和正式测试ID沿用。针对该数据新增同工具安全/危险反例需要额外标注与验证，属于新的数据扩展实验。

逐动作审计核对缓存监督与原数据一致，训练/校准可见前缀标签冲突0组，跨训练/校准相同前缀99组。跨域模型效果修复仍待完成。下一步可验证开发集上的执行顺序、首个危险边界以及风险头的参数敏感性；未经核实不得把任意合成工具调用赋安全标签。

### 共同划分复核（2026-11-26）

依据 DreamGuard 论文附录 C.3，两种方法在本地对照中共用训练、校准和测试 ID。新清单 `splits/safetydrift-public-shared-v1.json` 使用既有 DreamGuard 可见输入去重结果，排除 TRACES 旧训练清单中的一条重复轨迹。服务器逐条核对通过，两个加载入口均得到 221/57/72 条相同 ID、标签和首次危险步。校准和测试列表及顺序与公开固定清单一致。DreamGuard 从旧、新清单加载的实际模型输入完全相同。

作者清理后的 ID、最终 Scheme-D 权重和阈值、以及论文 TRACES 基线的完整运行配置仍未找到可核实的发布材料。共同划分对齐是本地对照修正。已有 96.00% 属于旧 222 条训练配置，新清单的正式 TRACES 指标待运行。

```bash
cd /data1/yaoziao/agentguard
TRACES_DIAGNOSTIC_GPU=0 TRACES_DIAGNOSTIC_SPLIT=splits/safetydrift-public-shared-v1.json \
  bash scripts/run-traces-scenario-diagnostic.sh
```

GPU 编号按启动时空闲卡替换。脚本依次训练、评估和核验，输出位于 results/traces-safetydrift-public-shared-v1-时间戳。DreamGuard 如另行重训，可向原 launcher 追加 --safetydrift-split splits/safetydrift-public-shared-v1.json 并使用新的运行目录。

[DreamGuard 论文附录 C.3](https://arxiv.org/html/2608.05695v1#A3.SS3)
