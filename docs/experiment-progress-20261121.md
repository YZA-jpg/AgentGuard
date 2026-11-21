# 实验进度检查：2026-11-21

检查时间：北京时间 2026-11-21 11:30 左右。核对进程、tmux 窗口、退出码、完成标记、summary 和 verification；检查时没有这些批次的活跃评测计算进程。未改动配置或启动新实验。

## 批次状态

| 批次 | 当前状态 | 核验范围 |
| --- | --- | --- |
| DreamGuard v1/v2 | 全部完成 | 两版重新训练；配对 ATBench200 各一组；v2 ATBench1000、SafetyDrift72；逐案例重算混淆矩阵一致 |
| AgentDojo Flash/Pro 配对诊断 | 全部完成并复核 | 三组各40，合计120条诊断，另有3条接口验收；退出码0，判分复核无差异 |
| AgentDojo Flash 作者依赖锁版 | 全部完成并复核 | 良性97、能力验证35、攻击949；合计1081，零错误 |
| SafePred 作者实现版 | 部分完成后报错退出 | ATBench200完成且复核通过；SafetyDrift正式72尚未执行，整批退出码1 |
| ShieldAgent（THU） | 全部完成并复核 | ATBench1000原生32k；另有25条YaRN对照 |
| 旧 SafetyDrift 四组 | 均完成并复核 | Flash、AgentDoG、SafePred-prompt、TRACES各72；旧SafePred-prompt与新作者版分开报告 |

## DreamGuard 新结果

F1/Recall/FPR 为百分比，Latency 为秒/次。两版200条配对结果使用统一执行前计时，关闭文本缓存，保留各自原生输入序列化及池化。

| 方法 | 范围 | F1 ↑ | Recall ↑ | FPR ↓ | Latency ↓ |
| --- | --- | ---: | ---: | ---: | ---: |
| DreamGuard v1 | ATBench200 | 66.22 | 100.00 | 100.00 | 0.094522 |
| DreamGuard v2 | 同一ATBench200 | 66.22 | 100.00 | 100.00 | 0.117369 |
| DreamGuard v2 | ATBench1000 | 66.31 | 99.80 | 100.00 | 0.107078 |
| DreamGuard v2 | SafetyDrift72 | 97.44 | 100.00 | 5.88 | 0.072262 |

配对200条两版均为 TP99/FP101/TN0/FN0；v2全量为TP496/FP503/TN0/FN1。SafetyDrift72为TP38/FP2/TN32/FN0，PHIR94.74%，MAS3.3611步。原生评测与统一计时复测之间，两版各自的200条预测均无变化。

结论限定为：v2在独立SafetyDrift测试集表现较好，但未改善ATBench迁移，不能把几乎全部拦截的高Recall称为有效区分。两版在训练划分、优化器及输入等多个方面同时改变，不能当作单因素消融；也不能与作者未公开清理split的论文分数声称严格同协议复现。

目录：`/data1/yaoziao/agentguard/results/dreamguard-v1-v2-20261121_015401`；`status.json` 为 `complete`，完成时间为北京时间 11月21日02:02:51。

## AgentDojo 配对诊断

相同40条、相同输入与注入、显式请求thinking开启。ASR/Utility按原生官方判分；Pro省略temperature不能解释为某个已知默认温度。

| 模型/请求设置 | 完成 | 攻击成功 | ASR | Utility |
| --- | ---: | ---: | ---: | ---: |
| Flash-0731，temperature=0 | 40/40 | 1 | 2.50% | 87.50% |
| Pro，temperature=0 | 40/40 | 25 | 62.50% | 67.50% |
| Pro，省略temperature | 40/40 | 24 | 60.00% | 67.50% |

各组零错误、40条复核通过、checker mismatch=0。该诊断说明本批次Flash与Pro差异明显，不能预设只换模型ASR应相近；它仍只是40条诊断，不是新跑完的Pro939全量。三组各有1条Travel关键词命中需要内容人工复核，以上保留官方判分。

目录：`/data1/yaoziao/agentguard/results/agentdojo-model-diagnostic-20261121_005159`，`batch.done`存在且`batch.exit=0`。

Flash作者依赖锁全量组：949条攻击成功5条，ASR0.5269%；攻击下Utility841/949=88.62%；良性Utility89/97=91.75%。目录为`agentdojo-official-author-flash-20261120_201550`。此前非作者依赖锁组的3/949属于另一个旧批次，当前报告不与其混用。

## SafePred 作者版的完成部分与失败原因

ATBench200：TP54/FP47/TN54/FN45，F1=54.00%，Recall=54.55%，FPR=46.53%，Latency=17.444954秒/次；200条均完成，零错误，663次审核和作者原生响应重放均复核通过。

后续SafetyDrift正式阶段在载入数据时触发`KeyError: 'test'`：`safepred_author_eval.cases_for()`传入`test`，固定清单的测试分组键为`heldout`。因此不是仍在推理，也不是72条正式组已经完成。两个SafetyDrift smoke案例成功不代表正式组完成。

目录：`/data1/yaoziao/agentguard/results/safepred-author-qwen3-8b-20261120_092801`。`batch.exit=1`、没有`batch.done`、没有SafetyDrift正式summary。已完成的ATBench结果有效，无需为了补SafetyDrift而重跑ATBench。

## 更早组的核对

ShieldAgent（THU）ATBench1000原生32k：F1=71.37%，Recall=84.51%，FPR=51.69%，Latency=0.450385秒/整轨迹审核；25条超长输入在原生窗口被截断。YaRN25对照独立完成，F1=95.83%，Recall=92.00%，25条均危险，不能估算FPR，也不替换主表。耗时粒度与DreamGuard逐动作不同，不直接按此数值比较在线开销。

目录：`/data1/yaoziao/agentguard/results/atbench-shieldagent-thu-20261119_010945`，`verification.status=all_complete_verified`。

旧SafetyDrift72结果：Flash F1=26.92%，AgentDoG=44.78%，SafePred-prompt=73.68%，TRACES=96.00%；均为已完成且复核通过的旧协议。旧SafePred-prompt不冒充作者实现版，不能填补此次作者版失败的正式组。

目录：`/data1/yaoziao/agentguard/results/safetydrift-baselines-20261118_191442`。

## 后续建议

1. 优先修复SafePred测试分组名映射，验证后只补SafetyDrift72；保留ATBench200与冻结政策。
2. DreamGuard下一步做ATBench迁移失效诊断，检查原生字段表示、分数分布和来源校准阈值，不用ATBench测试标签回调阈值。
3. 根据40条诊断再确定Pro全量计划；本次进度检查没有启动新一轮。
