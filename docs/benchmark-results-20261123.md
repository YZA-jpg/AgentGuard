# ATBench 与 AgentDojo：最新结果及补测

核对快照：2026-11-23T12:15:47+08:00（北京时间）。只纳入当前注明协议的结果；旧手写 SafePred-prompt、TRACES K32、IPIGuard 旧 AgentDojo 协议不混入本表。完成运行与复现论文数值是不同结论。

## 本轮补测

- ShieldAgent-THU / SafetyDrift 原测试72：完成并核验，零错误。TP/FP/TN/FN=19/16/18/19；F1 **52.05%**、Recall **50.00%**、FPR **47.06%**、Latency **0.3094秒/审核**。333次审核，无输入截断、无失败重试；PHIR36.84%、MAS4.1429步；缺少恢复动作标签，recovery FPR为空。
- AgentDoG / Pro回放：只重试 Banking 的 `under_attack--banking--user_task_6--injection_task_1`，仍在第3次审核缺少判定标签。1024输出上限的主协议保持1045条有效、1条错误。原1045条成功记录原样保留，新合并视图逐前缀/决策重算核验，状态为 `complete_with_errors_verified`；原始结果未覆盖。
- AgentDoG 2048输出上限独立诊断也已完成，但仍缺少判定标签。原失败输出重新分词为1024 tokens，确实触及原上限；延长至2048仍未恢复有效输出。该诊断不混入1024主协议，不把模型未给出标签算成安全或拦截。
- TRACES K8 的统一留出200配对补测已于11月22日21:36:48完成并核验，零错误。保持原200测试ID与200校准ID，训练集中仅排除作者动作提取不适用的908，训练599条；原作者两阶段训练，固定阈值0.3，不在测试集上选阈值。TP/FP/TN/FN=73/20/81/26。
- 原 SafePred / Pro1046回放继续运行，当前1003/1046，1003条均为ok；未重启或改动原任务。
- 两路补测的总退出码1来自AgentDoG重复的解析错误；ShieldAgent formal72已独立完整通过，不需要因整批退出码重复运行。

## ATBench：统一留出200条

测试清单沿用 `splits/atbench-v1.json` 的同一200条，99危险、101安全。下列正式输出均完整、零错误；TRACES派生清单仅在训练分组排除908，未改变测试或校准ID。

| 方法 / 配置 | 评分方式 | TP/FP/TN/FN | F1 ↑ | Recall ↑ | FPR ↓ | Latency ↓（秒/审核） |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Pro零样本安全判别（AgentDoG模板） | 完整轨迹 | 74/36/65/25 | 70.81% | 74.75% | 35.64% | 15.9246 |
| AgentDoG 1.5 4B，作者格式、1024输出 | 完整轨迹 | 79/37/64/20 | 73.49% | 79.80% | 36.63% | 17.5247 |
| ShieldAgent-THU，官方权重、原生32k | 完整轨迹 | 80/59/42/19 | 67.23% | 80.81% | 58.42% | 0.4027 |
| SafePred作者核心＋原始Qwen3-8B | 逐步、首次拦截 | 54/47/54/45 | 54.00% | 54.55% | 46.53% | 17.4450 |
| DreamGuard v2，独立方法复现 | 逐步、首次拦截 | 99/101/0/0 | 66.22% | 100.00% | 100.00% | 0.1174 |
| TRACES K8，固定阈值0.3、统一200划分 | 整轨迹末状态 | 73/20/81/26 | 76.04% | 73.74% | 19.80% | 0.2402 |

同一测试ID允许比较轨迹分类指标，但逐步一次审核与整轨迹一次审核输入长度不同，Latency不直接代表相同在线开销。DreamGuard在该200条上全部判危险，FPR100%，不能将其高Recall解读为有效防护。ATBench没有可靠的独立恢复动作标签，recovery FPR为空。

Pro这一行已经是普通零样本检测：没有护栏专用权重、训练或世界模型，只借用AgentDoG作者coarse提示和序列化。70.81%低于AgentDoG73.49%与TRACES76.04%，高于另外几组并不构成评测错误。骨干能力、完整轨迹信息与逐步审核、专门训练模型跨域迁移均有差异，不能据此保证专用方法一定更高。

当前建议保留该强基线，透明注明模板。如果补普通提示组，应使用同一200条、同样工具schema、同一Pro、temperature0、thinking关闭、1024输出，仅替换提示并单列；不能为了使基线分数更低而替换现组。旧简化组还同时改变工具信息和输出上限，不能当作只改变提示的实验。

## ATBench：其他范围，分别报告

| 方法 / 配置 | 测试范围 | F1 ↑ | Recall ↑ | FPR ↓ | Latency ↓（秒/审核） |
| --- | --- | ---: | ---: | ---: | ---: |
| ShieldAgent-THU，原生32k | 全量1000 | 71.37% | 84.51% | 51.69% | 0.4504 |
| DreamGuard v2，方法复现 | 全量1000 | 66.31% | 99.80% | 100.00% | 0.1071 |
| TRACES K8，阈值0.3，既有作者算法重建划分 | 另一组200 | 80.54% | 89.90% | 32.67% | 0.2408 |

TRACES既有200与统一200只重叠34条，80.54%不填入配对主表，新的配对值为76.04%。新组校准集搜索候选最优阈值约0.07，但正式评测按预先冻结的作者README阈值0.3，未采用该候选。不能把新旧TRACES的差异当作只改变K的消融。Shield原生全量中25条输入截断，配对200中3条截断；独立YaRN长25对照F1=95.83%、Recall=92.00%、Latency=19.4276秒，全部为危险轨迹所以FPR未定义，且不替换原生32k主结果。AgentDoG和SafePred作者核心目前完成的是200条，未据此宣称全量1000。

DreamGuard v1与v2在同一200条上的F1均66.22%、Recall/FPR均100%；各自延迟0.0945/0.1174秒。v1使用不同训练/校准划分，未保留独立SafetyDrift测试集，不能把其校准集当测试集。

## AgentDojo：原生在线、无护栏基线

官方AgentDojo0.1.35/v1.2.2、作者依赖锁；每模型1081=97良性＋35能力验证＋949攻击，均零错误、官方checker逐条复核通过。四个suite为workspace/slack/travel/banking。本轮攻击只覆盖作者 `important_instructions`。

| Backbone | 完成 | 攻击成功 / 949 | ASR ↓ | 攻击下Utility ↑ | 良性Utility ↑ | 能力验证Utility ↑ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Flash-0731 | 1081/1081 | 5 | 0.53% | 841/949，88.62% | 89/97，91.75% | 31/35，88.57% |
| Pro | 1081/1081 | 459 | 48.37% | 571/949，60.17% | 84/97，86.60% | 33/35，94.29% |

共同请求设置：temperature=0、thinking=provider（请求不显式指定）、4个API工作进程、作者15轮预算、timeout180秒、外层最多2次尝试；不额外指定输出上限/top_p/seed，攻击显示称呼DeepSeek。两组均无实际任务重启；保留原生checker判分，攻击成功与用户任务成功可以同时成立。服务端实际模型快照及默认采样实现不由这些参数完全固定。

完整原生轨迹已保存。无独立动作安全真值，因此本表F1/Recall/FPR不适用；无护栏也没有护栏审核Latency。原来的96/935条旧适配实验不与当前97/949条原生协议混用。

## AgentDojo：在新Pro轨迹上的固定回放

范围为97良性＋949攻击=1046；35条能力验证不纳入护栏回放。源攻击中459条被官方checker判成功。冻结各护栏权重/提示/阈值，当前候选动作只看到先前已执行历史；首次BLOCK/HOLD停止。

| 护栏 | 有效完成 | 源成功攻击轨迹干预 | 全部攻击轨迹干预 | 良性任务轨迹干预 | Latency（秒/审核） | 错误数 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AgentDoG，1024输出主协议 | 1045/1046 | 457/458，99.78% | 685/948，72.26% | 62/97，63.92% | 16.2009 | 1 |
| ShieldAgent-THU，原生32k | 1046/1046 | 448/459，97.60% | 769/949，81.03% | 74/97，76.29% | 0.3878 | 0 |
| TRACES，SafetyDrift训练K8 | 1046/1046 | 419/459，91.29% | 781/949，82.30% | 73/97，75.26% | 0.0892 | 0 |
| DreamGuard v2，SafetyDrift训练 | 1046/1046 | 459/459，100.00% | 949/949，100.00% | 97/97，100.00% | 0.0871 | 0 |
| SafePred作者核心，Qwen3-8B | 运行中：1003/1046 | — | — | — | — | 当前0 |

**这里的干预比例不是Recall/FPR，也不是防护后的ASR/Utility。** 没有重执行环境、没有独立动作安全标签，且一次干预可能发生在源轨迹危害之后；不能从459次源攻击成功中减去干预次数来宣称攻击被阻止。新原生流程的真正在线护栏结果尚未完成。

Shield/TRACES分别干预74/97、73/97条良性任务轨迹；DreamGuard干预97/97，表明当前迁移配置干预很激进，需要关注任务损伤。AgentDoG的99.78%按458条有效源成功攻击计算，另外1条错误没有当作安全或成功拦截。

## AgentDojo：新增轨迹级分类F1

根据用户要求，新增CPU后处理的[完整分类表与重算方式](agentdojo-replay-classification-20261123.md)。它是项目自定义的“官方源成功攻击轨迹 vs 良性任务轨迹”分类；不替代上面的干预统计、原生在线ASR/Utility，也不等同ATBench的独立安全标签。

正类为官方checker判定攻击成功的459条源轨迹，负类为97条良性任务组；攻击失败不证明轨迹安全，另外490条不强标为安全。预测为回放中是否出现BLOCK/HOLD。主表在四个已完成方法共同有效的555条（458正、97负）上计算，所有方法共同排除AgentDoG解析失败的同一条，错误覆盖率仍单独报告。负类表示良性任务条件，不承诺每个动作都经过独立安全认证。

| 方法 | TP/FP/TN/FN | F1 ↑ | Recall ↑ | FPR ↓ | Balanced accuracy ↑ | 秒/审核 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| AgentDoG | 457/62/35/1 | 93.55% | 99.78% | 63.92% | 67.93% | 16.3513 |
| ShieldAgent-THU | 447/74/23/11 | 91.32% | 97.60% | 76.29% | 60.65% | 0.3672 |
| TRACES | 418/73/24/40 | 88.09% | 91.27% | 75.26% | 58.00% | 0.0909 |
| DreamGuard v2 | 458/97/0/0 | 90.42% | 100.00% | 100.00% | 50.00% | 0.0874 |
| 全部拦截参考 | 458/97/0/0 | 90.42% | 100.00% | 100.00% | 50.00% | — |

正类约占82.52%，全部拦截也有90.42% F1。因此必须连同FPR和类别比例报告，不能把高F1解释成高可用性。该表Latency只用同一555条的审核记录重算，与1046全批均值分母不同。干预若晚于源轨迹危害仍被计为轨迹检出，不能解读成提前预警或阻止攻击。SafePred目前1003/1046，未用不完整结果参与正式排名。

## 配置说明

- AgentDoG：官方1.5 4B revision3193b58，作者coarse模板，BF16/greedy，1024输出。作者示例512输出与本项目1024稳健性设置的差异保留。
- ShieldAgent：THU Agent-SafetyBench官方7B模型及scorer，模型revisiona62f841、源码74feea8；它不是同名ICML策略电路方法。原生32k、FP16/SDPA、greedy10输出、batch1、FFN分块1024。SafetyDrift仅适配环境/角色/候选动作，未改变作者判别提示或训练权重。
- SafePred：不再使用手写prompt版；作者核心495890e＋原始Qwen3-8B(b968826)，作者完整流程提取并冻结政策；temperature0.3、seed42、thinkingfalse、4000输出、root0.7、penalty0.8、历史最多7条。未取得论文蒸馏权重，固定轨迹不执行actor重规划。
- TRACES：作者代码87579ab、Qwen3-4B第32层(1cfa9a7)、K8；ATBench既有组及本次配对组用固定0.3、StageA/B各30epoch。AgentDojo回放用SafetyDrift训练的K8与源校准阈值0.8，未在AgentDojo调参，不与ATBench模型混称。
- DreamGuard：独立论文方法复现v2，无可核验作者checkpoint；SafetyDrift221训练/57校准，冻结Qwen3-4B-Instruct-2507编码器、潜在世界模型和风险头，阈值不在ATBench/AgentDojo调优。其跨数据集全拦截问题仍未解决。

所有延迟为对应运行环境的平均审核耗时，排除模型加载；不宣称等同论文硬件/优化后速度。TRACES和DreamGuard的内置输入长度限制仍生效，回放摘要中的0截断计数不能证明其后端从未截断。

## 结果路径与查看

服务器统一根目录：`/data1/yaoziao/agentguard/results`。

| 数据 | 相对路径 |
| --- | --- |
| AgentDoG ATBench200 | `atbench-agentdog-author-heldout-1024-20261115_221521.jsonl` |
| Pro判别 ATBench200 | `atbench-deepseek-author-20261116_091817_909064276.jsonl` |
| Shield ATBench1000/200 | `atbench-shieldagent-thu-20261119_010945/formal` |
| SafePred ATBench200 | `safepred-author-qwen3-8b-20261120_092801/atbench-formal` |
| TRACES 既有独立200 | `atbench-traces-20261116_091817-paper-k8.jsonl` |
| TRACES 新配对200 | `atbench-traces-paired-k8-20261122_212853` |
| DreamGuard v1/v2 | `dreamguard-v1-v2-20261121_015401/comparison.json` |
| AgentDojo Flash原生无护栏 | `agentdojo-official-author-flash-20261120_201550` |
| AgentDojo Pro原生无护栏 | `agentdojo-official-author-pro-20261121_114813` |
| 五护栏Pro回放 | `agentdojo-pro-guard-replay-20261122_011126` |
| AgentDoG补测/合并、Shield SafetyDrift72 | `guard-makeups-20261122_212027` |

原始结果、轨迹与密钥不入Git。源码、参数及本报告备份到用户AgentGuard仓库。

查看长任务（服务器执行）：

```bash
cd /data1/yaoziao/agentguard
# TRACES统一200已完成：查看指标和核验，不再需要attach已结束的会话
cat results/atbench-traces-paired-k8-20261122_212853/state.json
cat results/atbench-traces-paired-k8-20261122_212853/summary.json
cat results/atbench-traces-paired-k8-20261122_212853/verification.json
# 原SafePred批次进度
cat results/agentdojo-pro-guard-replay-20261122_011126/safepred/formal/progress.json
tmux -S cache/tmux/pro-guard-replay.sock attach -t pro_safepred
```

测试过程：本地/服务器各通过5项补测完整性测试、8项原生回放测试、5项SafetyDrift数据/因果边界测试；同步文件SHA256一致。新增加独立入口，不修改原SafePred运行逻辑。

