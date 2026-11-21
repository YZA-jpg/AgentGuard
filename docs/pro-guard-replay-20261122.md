# 新 Pro 轨迹上的五种护栏回放

本批次由用户于2026-11-22授权启动。输出目录：`/data1/yaoziao/agentguard/results/agentdojo-pro-guard-replay-20261122_011126`。

## 输入和口径

源为已验证的`agentdojo-official-author-pro-20261121_114813`，官方AgentDojo0.1.35/v1.2.2、无护栏Pro、`important_instructions`。共同输入为97条良性及949条攻击轨迹，其中原无护栏攻击成功459条；35条能力验证不混入护栏比较。

原生轨迹共6781个已执行工具动作与最终回复审核点。另有5个因作者工具循环预算结束而未执行的pending调用，保留覆盖计数，排除出已执行来源动作。源数据没有query restart；适配器会拒绝含restart的数据，以免漏掉已执行历史。

所有方法共享同一bundle及SHA256。每次审核只接收当前候选和此前已经执行的历史，当前动作结果在审核后才加入。多工具调用按原生顺序处理，前一个调用已返回的结果可供后续调用审核。候选参数使用原生运行时解析后的参数，不传入其执行结果。最后的自然语言回复也审核，避免遗漏文字推荐等攻击。

原系统消息保存在记录中，并通过标注为`[Recorded agent system instructions]`的首个user字段暴露给仅支持user/agent/environment的作者格式器；实际用户任务单独保留。各方法仍遵循各自作者的字段编码：DreamGuard只编码用户任务、最近观测与动作，SafePred通过其全局政策保留系统规则。此类输入序列化属于跨基准适配，不能声称是作者未公开的AgentDojo具体提示模板。

## 方法和固定设置

| 方法 | 核心方法与本轮设置 | 资产来源和差异 |
| --- | --- | --- |
| AgentDoG1.5 4B | 专用安全分类器审核执行前前缀及候选；原作者coarse模板、BF16、greedy、1024输出tokens | 官方revision`3193b58d0c8924f5b5a79eb99cd31918e327024c`及模板；沿用先前已验证的1024稳健口径，作者示例512是另一个设置 |
| ShieldAgent-THU7B | 官方dialogue formatter、原生32k、10输出tokens、greedy、FP16/SDPA；FFN分块1024以控制临时显存 | THU Agent-SafetyBench checkpoint`a62f8413908bf3dbb1aea2edfbbeae54fdfd383c`，作者scorer`74feea8de601b3a1449a93fcf70017fe61556f73`；是THU判别模型，不是同名ICML政策电路系统 |
| SafePred作者核心 | 原生world-model提示/解析/评分/root；短/长期预测开启；temperature .3、seed42、thinking关闭、4000输出tokens，输入36960；惩罚.8、阈值.7、最近7条已执行响应 | 原始Qwen3-8B、作者代码`495890eafce02f9990e494493891c4549114a2dc`；先由作者完整政策抽取流程处理公共系统提示，冻结P000及其余生成政策后再审核；不重新使用SafetyDrift政策，不用攻击目标或测试结果写政策；不含在线重规划 |
| TRACES | 冻结观察器动作末token表示＋作者Stage-A/Stage-B轨迹模型；K8、第32层、7500-token左侧截断；阈值.8 | 复用SafetyDrift222/57训练/校准模型及其预先确定的`calibration_max_prefix_f1`阈值；作者默认.3是不同阈值口径；无AgentDojo调参或新训练 |
| DreamGuard v2 | 冻结Qwen表示＋RSSM后继预测、hazard/prefix双头及时间融合；逐案例独立会话，只有来源已执行的PASS动作提交状态 | 本项目已验证的论文方法复现版，SafetyDrift221/57训练/校准，固定checkpoint和阈值；不是作者发布权重；不在AgentDojo重校准 |

SafePred政策只输入固定、任务无关的官方原始系统提示；该提示主要是工具使用规范，P000负责用户目标对齐。作者没有发布与本批次完全匹配的AgentDojo政策包，因此政策来源与抽取记录全部保存。任何表现均不用于修改该政策或选择阈值。

每种方法先做固定seed42、每suite各1良性+1攻击的8条执行/解析验收，不按源攻击是否成功选样本；通过后评测全部1046条。模型每条轨迹重置状态，第一次HOLD/BLOCK或审核错误即结束该轨迹。错误保留为error，不默认安全。

GPU3单独运行SafePred政策抽取、验收与正式回放；GPU4先依次验收其余四种模型，全部接口验收通过后再依次正式运行。每张卡只有一个本批次大模型实例，不与另一进程共享轨迹状态。服务器其他已有进程保持原状，延迟应按共享服务器实测解释。

## 指标及解释

- 原成功攻击轨迹拦截率：459条源攻击成功轨迹中，当前护栏发生干预的比例。它不证明干预早于攻击目标达成。
- 全部攻击轨迹拦截率：949条源攻击轨迹中的干预比例，不将所有攻击轨迹当危险动作真值。
- 良性轨迹拦截率：97条来源良性任务中的干预比例，不冒充独立动作级FPR。
- 审核耗时（秒/次）、审核调用数、截断数、错误数及各组实际有效覆盖量。
- F1、Recall、FPR、ASR、护栏下Utility及recovery FPR留空；计算这些指标需要独立安全标签或真正的在线环境重跑。

当前是固定轨迹回放：不执行工具、不调用Pro生成替代行动、不根据拦截改写后续环境。与前一轮建议的在线ASR实验是两个阶段，不能用本表的拦截数扣减459来声称防护后ASR。

## 文件与核验

- `bundle.json`：冻结共同输入、工具schema、来源配置与文件哈希。
- `METHOD-state.json`、`METHOD-process.json`：该模型当前阶段及子进程。
- `METHOD/smoke`、`METHOD/formal`：manifest、逐案例审核JSONL、progress、summary及verification。
- `safepred/policy`：系统规则来源、作者抽取完整记录与冻结政策。
- `comparison.md/json`：自动更新的五方法比较，未完成组显示queued或当前阶段。
- 根目录`batch.done`：五组正式数据均完成、零错误且通过核验后才产生。

核验会重新构造每一个可见前缀并比对哈希，重算汇总，检查首次干预停止规则。AgentDoG/Shield使用原判别解析器重核答案，TRACES按固定阈值重核，DreamGuard重算时间融合；SafePred额外用保存的响应重放原作者提示、解析和风险决策，不再调用模型。

8项CPU测试及真实Pro数据覆盖核验已通过，测试覆盖未来结果隔离、工具对应、自然语言终答、pending排除、状态重置、指标命名及结果篡改检查。论文/作者资产来源：[AgentDoG](https://github.com/AI45Lab/AgentDoG)、[ShieldAgent-THU](https://huggingface.co/thu-coai/ShieldAgent)、[SafePred](https://github.com/YurunChen/SafePred)、[TRACES](https://github.com/lab-flair/TRACES)、[DreamGuard论文](https://arxiv.org/html/2608.05695v1)。

```bash
cd /data1/yaoziao/agentguard
batch=results/agentdojo-pro-guard-replay-20261122_011126
cat "$batch/comparison.md"
cat "$batch/agentdog-state.json"
cat "$batch/safepred-state.json"

tmux -S /data1/yaoziao/agentguard/cache/tmux/pro-guard-replay.sock attach -t pro_guards
tmux -S /data1/yaoziao/agentguard/cache/tmux/pro-guard-replay.sock attach -t pro_safepred
```

本批次由助手代为启动，无需再次运行启动器。接口失败会停止对应lane的正式阶段，保留日志供修复；不要将失败或部分输出当成全量结果。
