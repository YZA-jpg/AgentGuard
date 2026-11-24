# SafePred分数、政策语义与论文参考核查

2026-11-24只读审计：读取已保存的ATBench200、SafetyDrift72、AgentDojo1046记录及固定版本作者评分函数；未启动模型推理，没有修改政策、阈值或旧结果。

## 全量AgentDojo的低干预率不等于低准确率

SafePred干预全部518/1046（49.52%）、攻击496/949（52.27%）、良性22/97（22.68%）。源成功攻击中干预381/459（83.01%）；源未成功攻击中干预115/490（23.47%）。因此攻击总干预率受到490条源未成功轨迹影响，不能当作Recall。低良性干预表明比其他几组更克制，但未干预78条源成功攻击；发生干预也不证明及时阻止攻击。

## 原生评分链：不是连续风险阈值问题

作者固定版本`YurunChen/SafePred@495890e`的`LLMBasedWorldModel._calculate_risk_score_by_rules`：有任何`violated_policy_ids`则赋固定penalty，否则0。当前penalty0.8、root阈值0.7。

| 数据 | 保存审核数 | risk=0 | risk=0.8 | 有违规ID却放行 | 无违规ID却拦截 |
| --- | ---: | ---: | ---: | ---: | ---: |
| SafetyDrift72 | 541 | 533 | 8 | 0 | 0 |
| ATBench200 | 663 | 562 | 101 | 0 | 0 |
| AgentDojo1046 | 4625 | 4107 | 518 | 0 | 0 |

所以0.7降至0.5不会改变这些保存输出的决策。当前低检出主要出现在模型识别/引用违规政策之前，而不是风险超过阈值后未拦截。SafetyDrift6TP/2FP/32TN/32FN，38危险仅检出6；零错误、零截断、零输出上限命中，不能用执行失败解释漏检。

## 已确认的政策适配缺陷

SafetyDrift冻结文件`policies/frozen/safepred-author-qwen3-8b-20261120/safetydrift.json`只有P000和P001。P000为作者自带目标一致性；P001的scope是SafetyDrift标注过程，description主要描述工具级标注及局限。它没有形成充分明确的agent行为安全约束。来源`policies/sources/safetydrift-author-global-rules.txt`主要是README的标注方法/局限，虽然不使用测试标签，但政策源文档本身选取不足。

SafetyDrift的8次拦截中，5次仅P000、3次仅P001。此前原生执行/响应重放和结构验收通过，不能证明政策语义正确；这部分验收不充分。结果数字可重算，但当前政策适配不应作为严格论文复现配置验收通过。

AgentDojo冻结政策由官方通用系统提示抽取，P001主要约束参数消歧、查询无结果后换查询、不要假设当前年份；缺少明确覆盖数据外发、授权边界、工具输出指令信任的专门约束。518次拦截中479次仅P000、34次P000+P001、5次仅P001，即513次涉及P000。该证据说明当前审核高度依赖目标偏离识别；不能量化各缺陷对最终分数的独立贡献。

ATBench政策P001为规范性安全定义和taxonomy，与上述标注方法P001不同，不能把SafetyDrift缺陷直接当成ATBench54% F1的唯一原因。

## 原论文与参考分数

[SafePred原论文](https://arxiv.org/html/2602.01725v1)主实验在OS-Harm/WASP，GPT-4o执行agent、Qwen3-Max护栏，报告PCR/SR/SUP；另评原始Qwen3-8B与蒸馏SafePred-8B。当前原始Qwen3-8B不是Qwen3-Max，也不是蒸馏权重；固定轨迹没有执行动作重生成或计划优化。temperature0.3与历史7条对齐，不足以声称整体配置相同。

用户给定SafePred45.3、TRACES87.1、DreamGuard96.4均可在[DreamGuard论文Table1](https://arxiv.org/html/2608.05695v1#S4)的SafetyDrift列找到。该文公开适配原则，但未取得可逐项核对的SafePred完整模型/政策/清理split包，不能默认它与当前原始Qwen3-8B设置相同。

| 指标 / SafetyDrift | DreamGuard论文SafePred行 | 当前作者核心适配 |
| --- | ---: | ---: |
| F1 | 45.3% | 26.09% |
| SR / Recall | 37.0% | 15.79% |
| FPR | 44.4% | 5.88% |
| 秒/审核 | 7.686 | 21.7127 |

数值并不一致：当前比参考更少报警、更多漏检；延迟也不同，硬件、骨干和输入协议未匹配。不能用AgentDojo全轨迹干预率49.52%对比SafetyDrift F1 45.3%。

## 与用户参考的接近程度

| 方法 / 数据 / 指标 | 用户参考 | 当前 | 差值（百分点） |
| --- | ---: | ---: | ---: |
| AgentDoG1.5 / ATBench / F1 | 74.30% | 73.49% | -0.81 |
| AgentDoG1.5 / ATBench / Recall | 80.30% | 79.80% | -0.50 |
| SafePred / SafetyDrift / F1 | 45.30% | 26.09% | -19.21 |
| TRACES / SafetyDrift / F1 | 87.10% | 96.00% | +8.90 |
| DreamGuardv2 / SafetyDrift / F1 | 96.40% | 97.44% | +1.04 |

AgentDoG当前200留出与参考范围未完全匹配。SafetyDrift公开版72及本地去重划分也未核验为DreamGuard论文清理后的完整划分。TRACES显著高于参考需要查划分/场景重叠/阈值，不能仅视为复现更好；DreamGuard源域接近参考不抵消跨域失效。数值差只用于核对，不通过测试调参追逐参考分数。

## 建议的下一步（未执行）

1. 先验收SafetyDrift和AgentDojo政策源：把规范性安全约束与标签生成方法分开；按作者工作流提取并检查语义。不得从测试失败样本/预期标签反推规则。新政策必须另版本、预先冻结。
2. 保持原始Qwen3-8B、评分逻辑和采样不变，在独立开发样本上验证政策覆盖，再单列新旧政策对照；不要同时更换骨干，以免无法解释变化。
3. 另组补Qwen3-Max或可核验SafePred-8B权重，核对DreamGuard基线资产，作为模型差异对照。原论文完整在线决策优化与离线检测结果分开。
4. 对比参考前冻结数据ID、标签、阈值和指标口径；AgentDojo保留全量回放统计，真实防护ASR需在线实验。

只读计数脚本位于服务器`/data1/yaoziao/agentguard/cache/audit_safepred_scores_20261124.py`。本次仅核查保存结果，未运行新实验。
