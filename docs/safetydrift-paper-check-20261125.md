# SafetyDrift 复核（2026-11-25）

最终任务为固定测试集72条上的逐动作、执行前审核。首次 HOLD/BLOCK 计轨迹阳性。分类报告 F1、Recall、FPR，时序另列 PHIR、MAS，端到端延迟单位为秒/审核。论文未提供已核实的同一份清理后 ID 清单。本文的百分点差异是跨报告的描述性差异。

| 方法 | 本地 F1 / Recall / FPR | DreamGuard 表1 F1 / SR / FPR | 本地秒/次 |
|---|---|---|---:|
| SafePred，原始 Qwen3-8B、政策 v2 | 8.89 / 5.26 / 14.71 | 45.3 / 37.0 / 44.4 | 17.968 |
| TRACES，SafetyDrift 内训练 | 96.00 / 94.74 / 2.94 | 87.1 / 96.3 / 33.3 | 0.0808 |
| DreamGuard v2，独立训练 | 97.44 / 100 / 5.88 | 96.4 / 96.3 / 3.7 | 0.0723 |

SafePred 官方合并权重已落在 data1 的 models/safepred-8b-author。版本 430a412fa7d055fa5c8348e73d9fe20ac251949a。入口 agentguard.safepred_distilled 对照冻结 v2 政策和原状态映射，固定 temperature 0.3、历史7、单候选、最大4000输出、关闭 thinking。45.3 来自 DreamGuard 的基线实验，论文未逐项给出其 SafePred 推理配置。正式命令在服务器项目根目录执行：

```bash
tmux new-session -d -s safepred8b_sd72 'cd /data1/yaoziao/agentguard && env -u LD_LIBRARY_PATH CUDA_VISIBLE_DEVICES=4 HF_HUB_OFFLINE=1 OMP_NUM_THREADS=2 .venv/bin/python -u -m agentguard.safepred_distilled --out-dir results/safepred8b-sd72-$(date +%Y%m%d_%H%M%S)'
```

DreamGuard 对照沿用冻结权重、校准57和测试72。固定种子20260701，分别按 argmax 或分类采样推断潜状态，再用对应推断模式在源校准集确定阈值。两者都是 TP38/FP2/TN32/FN0、PHIR 94.74%，MAS 从3.36变为3.64。论文 PHIR 96.3%、MAS 3.63。此次只比较分类与时间步，缓存特征计时不进入主表。ATBench 固定开发集6安全＋6危险，两种推断仍然全部干预。该改动未达到跨域修复目的，保留原主表。结果在 results/dreamguard-latent-paired-20261125。此前目标域单独校准后 heldout200 的 FPR 8.91%、Recall 6.06%，提示特征区分能力有问题。下一步在开发域比较相同任务、相同动作而历史不同的配对，并核对与作者的序列化和校准配置。

TRACES 复用作者两个阶段，K=8、原观察器第32层，使用校准集最大前缀风险选阈值0.8。当前TP36/FP1/TN33/FN2，Recall略低于论文，FPR低30.36个百分点。原评测实现采用自己的SafetyDrift适配。37个测试场景都在训练集出现，35条测试轨迹有训练中相同早期事件前缀。场景多数规则得到97.30% F1。因此需要同场景异标签配对和逐ID论文split核对。详见 [训练资产审计](safepred-policy-v2-traces-audit-20261124.md)。

[DreamGuard 原文与附录](https://arxiv.org/html/2608.05695v1) · [SafePred 作者权重](https://huggingface.co/yurun-chen/SafePred-8B)
