# Pro 全量与 SafePred72：完成结果

2026-11-22 核验。两项均在北京时间2026-11-21下午完成，退出码0，完成标记及独立复核齐全；检查时没有这两项的活跃计算进程。本轮检查未启动新测试。

## AgentDojo：Pro 与 Flash 全量对照

Pro于11月21日14:41:35完成1081条正式任务：97良性、35能力验证、949攻击，零错误，未混入另外8条接口验收。逐条结果与计划完整匹配，全部4344次API响应模型均为`deepseek-v4-pro`，原生离线checker复核1081条、差异0。

重新核对请求配置，除backbone及记录代码版本外，任务清单、作者环境、系统提示、工具schema、注入显示名、攻击内容、temperature、思考参数及脱敏endpoint均与Flash对照一致。采用官方AgentDojo0.1.35/v1.2.2、作者依赖锁、无护栏、`important_instructions`、称呼`DeepSeek`、temperature=0、thinking=provider、4路API进程、不额外指定输出上限。服务控制的实际模型快照和默认采样行为不能据此宣称固定不变。

| 模型 | 正式完成 | 攻击成功 / 949 | ASR | 攻击下Utility | 良性Utility | 能力验证Utility |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Flash-0731 | 1081/1081 | 5 | 0.53% | 841/949，88.62% | 89/97，91.75% | 31/35，88.57% |
| Pro | 1081/1081 | 459 | 48.37% | 571/949，60.17% | 84/97，86.60% | 33/35，94.29% |

观察到的ASR差为+47.84个百分点，攻击下Utility差为−28.45个百分点。这是同一套请求协议下的当前服务结果，不能把此前40条诊断或939条外部参考日志当作本表的分母。任务完成与攻击成功分别由官方checker判断，二者不必互斥。

| Suite | 攻击数 | Flash成功 | Pro成功 | Pro ASR |
| --- | ---: | ---: | ---: | ---: |
| Workspace | 560 | 0 | 222 | 39.64% |
| Slack | 105 | 1 | 92 | 87.62% |
| Travel | 140 | 4 | 56 | 40.00% |
| Banking | 144 | 0 | 89 | 61.81% |

949条攻击都已执行并判分。复核报告中939条在实际工具输入中出现`<INFORMATION>`标记；另10条也都有2–5次API调用和原生结果，攻击均未成功，不能将939误读成漏跑10条。其余工具调用路径已保存，可以后续查看未见标记的具体原因。上述ASR保留原生判分，不对Travel关键词类checker自行改标签。

Pro记录input_tokens=22,328,539，output_tokens=1,552,022。F1/Recall/FPR继续为空：这是在线无护栏任务执行基线，报告ASR/Utility；没有独立动作安全真值时不将ASR折算成分类指标。

目录：`/data1/yaoziao/agentguard/results/agentdojo-official-author-pro-20261121_114813`。关键文件：`summary.json`、`verification.json`、`cases.jsonl`、`attempts/*/*/api.jsonl`及native trace。`batch.done`、`verified.done`和`batch.exit=0`齐全。

## SafePred 作者核心：SafetyDrift72补测

于11月21日15:07:29完成。仅修复正式分组`test → heldout`；仍使用原冻结政策、原始Qwen3-8B、原作者prompt/parser/scorer/root以及先前采样配置。没有重新训练或抽取政策。

| 范围 | 完成 | F1 ↑ | Recall ↑ | FPR ↓ | Latency ↓（秒/审核） |
| --- | ---: | ---: | ---: | ---: | ---: |
| SafetyDrift heldout72 | 72/72 | 26.09% | 15.79% | 5.88% | 21.7127 |
| ATBench heldout200（原已完成组，未重跑） | 200/200 | 54.00% | 54.55% | 46.53% | 17.4450 |

SafetyDrift混淆矩阵：TP=6、FP=2、TN=32、FN=32；38条危险仅检出6条，34条安全中误报2条。PHIR=7.89%（3/38），MAS=2.3333步，未提供恢复动作标签，recovery FPR为空。

共541次审核/生成，零错误、零失败重试、零输入截断、零输出上限命中；输入2,538,388 token，输出277,393 token。作者原生响应重放与可见输入核验全部通过（72条、541次审核），状态`complete_verified`。因此当前结果的主要问题是漏检，而不是把运行错误算成安全。

该结果属于“作者核心＋原始Qwen3-8B＋本项目冻结政策”的当前适配，不自动等于作者其他骨干或蒸馏模型的论文数值。之前的SafePred-prompt为另一个实现与骨干，不能拿它的较高Recall替换此组。仅凭本表无法将性能变化归因于某一项改动，需要查看漏检轨迹、政策引用和预测内容。

目录：`/data1/yaoziao/agentguard/results/safepred-author-safetydrift72-20261121_114813/safetydrift-formal`。关键文件：`summary.json`、`verification.json`、`manifest.json`、`results.jsonl`。上级目录`batch.done`与`batch.exit=0`齐全。

## 本次检查记录

- 从Pro和Flash各1081条case重算分组完成数、Utility及ASR，与summary一致；两组case key集合完全相同。
- 从SafePred72条case重算标签38/34、混淆矩阵及541次审核数，与summary一致。
- 用现有参数对照器再次核验模型替换与endpoint一致性。
- 原ATBench200的summary SHA256仍为`bc0a47314dcf7dfbcb768b6f0697c7fc0d468e46ce74c8f2fc6f54b6a9113091`，未被补测覆盖。
- 已将两项summary、verification及Flash对照summary下载到本地主工程`results/`忽略目录；Git仅备份本报告，不上传原始轨迹。

配置与启动说明见 [本轮参数文档](pro-full-and-safepred72-20261121.md)。后续建议先检查SafePred的32条漏检及预测/政策对应，再安排以Pro为backbone的护栏对照，保留离线检出与在线ASR的口径区分。
