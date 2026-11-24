# SafetyDrift 当前结果

核验：2026-11-24。六组均完成原固定测试集72条（38危险、34安全），各组零运行错误。输入是公开数据中已有的固定轨迹；Flash做逐步安全判别，不重新生成agent轨迹。首次HOLD/BLOCK将整条轨迹判为危险。

同日语义审计补充：SafePred数字和原生执行链已复核，但冻结P001主要描述标注方法、未充分形成行为约束，政策适配尚未通过语义验收。该行是当前适配结果，不能当成论文配置已完整复现。见[评分链与政策审计](safepred-audit-20261124.md)。

进一步审计：训练集场景多数标签在该72条上即可达到97.30% F1，类别多数标签92.31%，均不看动作。TRACES96%虽已验证无heldout训练特征，仍不能单独证明轨迹预警能力。新政策工具和场景/类别诊断见[修复与捷径审计](safepred-policy-v2-traces-audit-20261124.md)；新正式分数尚未产生。

| 方法 / 配置 | TP/FP/TN/FN | F1 ↑ | Recall ↑ | FPR ↓ | Latency ↓（秒/审核） |
| --- | --- | ---: | ---: | ---: | ---: |
| Flash-0731，通用安全判别 | 7/7/27/31 | 26.92% | 18.42% | 20.59% | 4.4420 |
| AgentDoG 1.5 4B | 15/14/20/23 | 44.78% | 39.47% | 41.18% | 13.3795 |
| ShieldAgent-THU，官方分类器 | 19/16/18/19 | 52.05% | 50.00% | 47.06% | 0.3094 |
| SafePred作者核心＋原始Qwen3-8B | 6/2/32/32 | 26.09% | 15.79% | 5.88% | 21.7127 |
| TRACES，作者代码、SafetyDrift训练K8、阈值0.8 | 36/1/33/2 | 96.00% | 94.74% | 2.94% | 0.0808 |
| DreamGuard v2，独立论文方法复现 | 38/2/32/0 | 97.44% | 100.00% | 5.88% | 0.0723 |

延迟包含该方法文本输入至判定的实际审核过程，排除模型加载；不同模型、输入格式及硬件优化不能当作同实现速度消融。没有独立恢复动作标签，recovery FPR均为空。

## 配置与解释

- SafePred当前表使用作者核心495890e、原始Qwen3-8B、冻结作者政策、temperature0.3、seed42、thinking关闭、4000输出、root0.7、penalty0.8、历史最多7条。尚未取得论文蒸馏权重；固定回放不执行actor重规划。旧手写SafePred-prompt的73.68% F1仅作历史对照，不填入当前正式行。
- TRACES先按作者代码在SafetyDrift训练，训练222、校准57、测试72；不是直接把ATBench训练模型称为SafetyDrift内训练。K8与源校准阈值0.8均冻结。
- DreamGuard v2有效训练221、校准57、测试72；多排除一条在实际输入投影上重复的训练记录。世界模型10epoch、风险监督12epoch，冻结官方Qwen3-4B-Instruct-2507编码器，其余为我们依论文实现和训练。当前97.44%不等于作者checkpoint结果。
- 保留测试ID并清理可见输入重复，但划分以轨迹为单位，未强制场景隔离；未核验到DreamGuard论文清理后的完整split资产。因此接近或超过论文参考分数，不能单独证明严格复现成功或跨场景泛化。
- ShieldAgent-THU指THU Agent-SafetyBench官方分类模型，不是同名ICML时序规则ShieldAgent。
- 本次11月24日两项修复没有改变任何SafetyDrift权重、阈值或测试结果。[修复结论与DreamGuard迁移失败](guard-repair-and-dreamguard-20261124.md)。

## 可追溯路径

服务器根目录均为`/data1/yaoziao/agentguard/`，原始结果不入Git。

| 方法 | 相对结果路径 |
| --- | --- |
| Flash、AgentDoG、TRACES | `results/safetydrift-baselines-20261118_191442/summary.json`中的对应methods；其中旧safepred行不采用 |
| ShieldAgent-THU | `results/guard-makeups-20261122_212027/shieldagent-formal/summary.json` |
| SafePred作者核心 | `results/safepred-author-safetydrift72-20261121_114813/safetydrift-formal/summary.json` |
| DreamGuard v2 | `results/dreamguard-v1-v2-20261121_015401/v2/safetydrift-native.jsonl`最后一条overall_summary |
| 本次只读汇总快照 | `results/guard-repair-20261124_115136/compact-status.json` |

