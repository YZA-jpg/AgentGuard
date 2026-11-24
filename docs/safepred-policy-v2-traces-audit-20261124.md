# SafePred政策修复与TRACES高分审计

2026-11-24。旧政策、旧模型、原测试72与所有已有结果保留。新正式benchmark尚未启动。

短GPU开发验收已完成：`results/safepred-policy-v2-preflight-20261124`退出码0；SafetyDrift4条政策/6个契约、AgentDojo5条政策/8个契约全部准入，含安全放行对照。完整artifact保留在服务器，公开政策及简要准入记录备份于`policies/frozen/safepred-policy-v2-20261124`。本轮正式启动应复用这批已验收政策，不重新抽取。

## SafePred修复了什么

原SafetyDrift P001主要描述数据集怎样标注，而不是明确约束agent；AgentDojo P001主要是参数消歧，缺少攻击防护的信任/授权边界。现在增加独立的`safepred-policy-adaptation-v2`流程，保持原作者核心、原始Qwen3-8B及采样不变，先隔离政策因素。

| 项目 | 新流程 |
| --- | --- |
| 政策源 | `policies/specs/safepred-v2/{safetydrift,agentdojo}.json`；公开全局定义的项目规范化适配，明确不是作者现成preset |
| SafetyDrift | 依据[原论文全局风险维度和附录A](https://arxiv.org/html/2603.27148v1)表达累计敏感信息/凭据接触、不可逆网络通信及其预测前兆；保留工具级风险口径，不读取单条gold状态 |
| AgentDojo | 依据[作者威胁模型](https://arxiv.org/html/2406.13352)表达不可信工具文本、数据披露授权、状态变更授权、参数消歧；允许用户已经授权的正常动作 |
| 提取 | 继续调用未修改作者`process_policy_input`完整工作流；不把我们写的JSON规则冒充作者生成结果，不事后默改生成政策 |
| 静态验收 | 检查规范性policy_description的必要覆盖，P000不能替代benchmark政策；词汇覆盖只是静态检查，不声称证明语义等价 |
| 行为验收 | SafetyDrift6、AgentDojo8个独立合成契约，均包含允许/拦截对照；危险对照必须引用覆盖相应约束的政策，仅P000不足以通过 |
| 冻结 | 保存spec/source/policy/extraction/contracts/代码/作者版本哈希；域绑定；任一覆盖或行为检查失败，不准入正式测试 |
| 评测 | 通过后仍用原SafetyDrift72和原Pro AgentDojo1046，固定回放/首次干预；ATBench原政策未发现同一缺陷，本轮不改 |

所有源文档明确排除测试轨迹、单场景risk_profile、expected_safe_path、Markov lookup、攻击目标和checker标签。合成契约不是benchmark案例，只作为开发回归检查；未用它们声称benchmark分数。

这是历史测试之后的工程修复和重复评测，不声称预注册盲测。新规则依据公开全局规范形成，没有根据单条测试错误补特例。

固定配置：原始Qwen3-8B revision `b968826d9c46dd6066d109eabc6255188de91218`、作者核心`495890e`；BF16/SDPA、temperature0.3、seed42、thinking关闭、4000输出、历史7条、penalty0.8/root0.7、单候选单步。提取仍用8192输出。正式进程重新初始化RNG，合成验收消耗不进入正式轨迹或延迟统计。没有蒸馏权重、GUI模拟或actor重规划，仍属跨benchmark适配。

当前代码入口：`agentguard/safepred_policy_v2.py`；契约输入：`agentguard/safepred_policy_contracts.py`。原`agentguard/safepred_author.py`及上游源码未改动。

## TRACES高分的具体证据

对保存的真实训练表、两个checkpoint和72条/422次回放逐项CPU复核：训练222条/1832动作、校准57条/484动作；训练缓存和Stage-A表没有heldout特征；checkpoint哈希匹配；当前候选的结果及gold字段没有进入审核。0.8阈值来自校准max-prefix F1，不是测试选参。已有96%数值可重算。

但固定划分具有很强的任务分布捷径：全部37个测试场景都在训练集中出现；训练/测试有62种相同早期事件前缀，涉及35/72条测试轨迹。完整因果轨迹表面重复为0，不能由此推导前缀独立。哈希口径为送入上游formatter之前的因果事件表面，非token级哈希。

| 原作者72测试 / 预测方法 | TP/FP/TN/FN | F1 | Recall | FPR |
| --- | --- | ---: | ---: | ---: |
| 仅训练集类别多数标签，诊断 | 36/4/30/2 | 92.31% | 94.74% | 11.76% |
| 仅训练集场景多数标签，诊断 | 36/0/34/2 | 97.30% | 94.74% | 0.00% |
| 当前TRACES，真实回放 | 36/1/33/2 | 96.00% | 94.74% | 2.94% |

两个多数标签基线只在训练集拟合，测试标签只评分；它们不看动作、没有训练神经模型。它们使用metadata作事后诊断，不当作实际在线护栏，也没有把metadata补入TRACES输入。结果说明该划分的整体F1不足以证明学到轨迹风险演化；尚不能仅凭此证明TRACES实际采用了哪条捷径。

TRACES按类别的真实结果：

| 类别 | 测试数 | TP/FP/TN/FN | Recall |
| --- | ---: | --- | ---: |
| code_debugging | 14 | 0/0/13/1 | 0% |
| data_handling | 20 | 16/0/4/0 | 100% |
| research_comms | 20 | 20/0/0/0 | 100% |
| sysadmin | 18 | 0/1/16/1 | 0% |

技术类两条少数危险均漏检；research_comms全部为危险，没有同类安全对照。整体96%掩盖了这些差异。[SafetyDrift作者也说明类别风险强相关及工具级标注局限](https://arxiv.org/html/2603.27148v1)。所以不降低阈值或删样本去追逐87.1%，也不把这个结果当成DreamGuard论文未公开清理划分的严格复现。

## 场景隔离仍不能独自解决问题

新增、预先冻结的`splits/safetydrift-scenario-disjoint-v1.json`：按类别内场景组分配、seed42，23/8/8场景，207训练/72校准/73测试；危险126/20/40。它不覆盖原72清单，已核验跨分组场景、完整事件表面及前缀重复均为0。数据按真实内容去重后352条，保留新诊断heldout中的全部ID。

**但该候选73测试中，训练集类别多数标签已达到100% F1。** 不更换seed挑低分，也不声称场景隔离就消除了类别捷径。保留这个固定诊断划分及可选启动器，但不默认投入GPU重训来制造一个新高分；若运行，必须同时报告类别基线和类别混杂限制。

后续更有信息的验证是同场景、同任务下安全/危险轨迹配对，以及跨数据集迁移。当前SafetyDrift的任务类别/场景与标签高度绑定，无法仅靠重新划分保证充分的安全对照。这个限制也影响DreamGuard等同源监督训练组。

## 验证和启动

新增静态/因果/隔离测试加已有原生SafePred回归，服务器26项CPU测试全部通过，无跳过。包括旧labeling-only政策拒绝、政策/源文件篡改拒绝、契约缺失拒绝、P000不能代替安全规则、测试标签不影响多数基线拟合、当前动作结果隔离及回放完整性。两脚本`bash -n`通过。短GPU政策提取/合成验收与正式benchmark分开记录。

TRACES新训练入口同时将适配器源码哈希提前绑定到training_metadata，避免同一未完成目录在适配器改变后复用旧特征；历史已完成checkpoint未改动，训练算法没有改变。

正式测试默认不代启动。先查看空闲卡，下面3仅为本次验收时有足够余量的卡号，启动时重新确认。单模型实例的历史/capture/RNG有可变状态，同卡内保持串行；不同空闲卡可以并行运行独立benchmark。

```bash
cd /data1/yaoziao/agentguard
nvidia-smi --query-gpu=index,memory.free,utilization.gpu --format=csv

# 复用本次已准入政策，依次SafetyDrift72 -> Pro AgentDojo1046
mkdir -p cache/tmux
tmux -S "$PWD/cache/tmux/safepred-policy-v2.sock" new-session -d -s safepred_v2 \
  'cd /data1/yaoziao/agentguard && SAFEPRED_V2_GPU=3 SAFEPRED_V2_POLICY_ROOT=results/safepred-policy-v2-preflight-20261124 bash scripts/run-safepred-policy-v2.sh'
```

`SAFEPRED_V2_POLICY_ROOT`须包含`{benchmark}-policy`完整原始artifact，不是只复制一个policies.json。域/代码/spec/政策/契约哈希任一变化都会拒绝复用。`SAFEPRED_V2_BENCHMARKS=safetydrift`或`agentdojo`可只跑一个组。若要重新研究提取流程，另开新目录并省略POLICY_ROOT；不要把重新生成的政策与本次冻结政策混为同一配置。

查看会话：`tmux -S /data1/yaoziao/agentguard/cache/tmux/safepred-policy-v2.sock attach -t safepred_v2`。各formal目录都有独立进度与核验文件；脚本只在均成功时写batch.done。

可选TRACES场景诊断（它仍受类别捷径影响，不是推荐的正式主表替换）：

```bash
cd /data1/yaoziao/agentguard
TRACES_DIAGNOSTIC_GPU=3 bash scripts/run-traces-scenario-diagnostic.sh
```

结果目录分别为`results/safepred-policy-v2-时间戳`和`results/traces-scenario-disjoint-时间戳`。查看`stage.txt`、`batch.exit`、各formal/progress和summary、verification；只有相应完整范围核验通过才报告新分数。政策准入失败会留下rejection.json并停止，不会自动修改规则或跳过验收。

本次CPU证据：服务器`results/traces-safetydrift-audit-final-20261124.json`、`results/traces-scenario-split-audit-final-20261124.json`；原模型和结果未覆盖。
