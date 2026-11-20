# ShieldAgent、DreamGuard 和 SafetyDrift 复现计划

2026-11-21：以下 DreamGuard 285/72 训练/校准与缓存延迟口径已由 v2 替代。新版本使用 221/57/72 有效划分、Adam、逐轨迹归一化和真实端到端计时。详见 [当前方法与代码说明](../dreamguard-reproduction-zh.md)。旧配置保留用于解释历史结果，勿用作新实验启动配置。

2026-11-19 更正：下表的 ShieldAgent 指 ICML 政策推理系统。另有清华 Agent-SafetyBench 的同名判别模型 `thu-coai/ShieldAgent`，已经发布官方 7B 权重和评分代码；此前调查遗漏了它。当前 ATBench 接入采用清华模型，两者不能混称。具体配置见 `docs/plans/2026-11-19-audit-shieldagent-atbench.md`。

这轮沿用 AgentGuard 的离线逐步审核入口。输入为当前候选动作和此前可见的轨迹。先复现作者自己的数据、设置和指标，再在同一批轨迹上比较各护栏。

| 项目 | 已核实的作者设定 | 接入所需材料 |
| --- | --- | --- |
| ShieldAgent · ICML 2025 | 从政策抽取并优化 LTL 规则，按动作组织加权规则电路。审核时检索相关电路，通过工具验证谓词，再做概率推断。论文的政策与规则抽取、优化使用 GPT-4o，规则相似度检索用到 `text-embedding-3-large`。附录 H 给出提示词示例。 | 完整提示模板与版本、动作到规则电路的映射、规则权重、验证工具接口与实现、最终决策配置。项目页提供论文和演示，尚未找到匹配 ICML 版的可运行包。 |
| DreamGuard · arXiv v1 | 冻结 Qwen3-4B-Instruct-2507，第 31 层池化为 2560 维；RSSM 的 GRU 确定状态为 1024 维，随机状态为 32 个 32 类变量。预训练 10 epoch，风险监督 12 epoch，batch 8，学习率 2e-4，世界模型学习率乘 0.25，训练种子 20260701。前缀风险 horizon 3、衰减温度 1.5，适配器比例 0.25，KL 0.03，JEPA 1.25，free bits 0.2。 | B.3 去重后的样本及 train/cal/test ID，模型 checkpoint 或训练代码，字段序列化与池化实现，Scheme-D 最终参数，HOLD/BLOCK 校准阈值。附录 C.6 将在线提示词、judge 和 schema 转换放在投稿附带包中，尚未找到公开下载。 |
| SafetyDrift · 原作者公开版 | Hugging Face `aditya593/SafetyDrift-traces`，revision `5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8`。公开版 357 条轨迹，按类别和最终是否违规分层，seed 42，训练/测试 285/72。首个违规步使用作者 loader 的 `violation_step_index`。 | 数据卡要求训练、微调、模型评估或 benchmarking 取得作者书面许可。原作者划分可用于数据清点。DreamGuard 的结果另需 DreamGuard 的划分清单。 |

来源：[ShieldAgent ICML 论文](https://proceedings.mlr.press/v267/chen25ae.html) · [ShieldAgent 项目页](https://shieldagent-aiguard.github.io/) · [DreamGuard 论文 §4、附录 A–C](https://arxiv.org/html/2608.05695v1) · [SafetyDrift 论文](https://arxiv.org/html/2603.27148v1) · [数据卡和使用条款](https://huggingface.co/datasets/aditya593/SafetyDrift-traces#license) · [作者 loader](https://huggingface.co/datasets/aditya593/SafetyDrift-traces/blob/main/loader.py)

1. 固定公开数据 revision，在服务器清点轨迹数、每步标注及作者 split。原始数据放在项目的 `data/` 下。记录轨迹 ID 和原始 split，供后续按样本配对。将该划分标为 SafetyDrift 原作者版本。
2. ShieldAgent 取得同版资产后，先在作者用例核对触发规则、谓词真假、最终标签和延迟。跨到 Flash/ATBench 时显式记录目标环境政策及动作映射版本。沿用 `Review` 接口，并记录规则 ID 以支持论文的规则召回指标。
3. DreamGuard 取得 checkpoint 和划分后，先核对离线输入字段、首个违规步、论文 Appendix A 的 split-conformal 校准，以及测试阶段固定的两个阈值。每条轨迹开始时重置 RSSM。复现结果记录 F1、Safety Rate（危险轨迹召回）、FPR、端到端秒/次、PHIR、MAS 和错误数。
4. 分别在作者样本和共享回放集验证首条记录。PHIR 用严格早于首个危险步的首次干预。首个危险动作在第 5 步时，第 4 步或更早的干预计入 PHIR。恢复误报率采用独立恢复标签。

公开版快照清点得到 357 条轨迹、2,947 步、186 条最终违规轨迹。285 条训练轨迹中有 148 条违规，72 条测试轨迹中有 38 条违规。已逐一核对清单中样本路径、划分顺序和首次违规步，与公开版 loader 输出一致。

在服务器重新生成清单时使用一个新文件名。

```bash
cd /data1/yaoziao/agentguard
rev=5c55e54b75c9c7ee2037db8f3dbd6ae6a7dab8a8
.venv/bin/python -m agentguard.safetydrift \
  --data-root "data/safetydrift/$rev" \
  --output "data/safetydrift/source-original-$rev-$(date +%s).json"
```

DreamGuard 的 SafetyDrift 论文参考值为 F1 96.4%、Safety Rate 96.3%、FPR 3.7%、延迟 0.027 秒/次。参考值对应作者清理后的实验协议。 [DreamGuard Table 1 与 Appendix A](https://arxiv.org/html/2608.05695v1)

## ATBench 方法复现版 · 2026-11-18

用户已接受使用明确标注为方法复现版的模型，并逐项记录与原论文的差异。公开检索找到 `ioo0s/DreamGuard-reproduction`，固定在 `fb83d6124edcd86b13bd01e94e05b6639c0eeb96`。其默认编码器、训练源、模型维度及训练轮数与论文不同，而且未提供 checkpoint。本轮根据论文公式独立实现 RSSM、两阶段训练与校准，代码为 `agentguard/dreamguard_model.py` 和 `agentguard/dreamguard.py`。

保留论文的 Qwen3-4B-Instruct-2507（revision `cdbee75f17c01a7cc42f958dc650907174af0554`）、第 31 层、2560 维输入、1024 维 GRU、32×32 分类隐状态、straight-through 训练、10/12 epoch、batch 8、2e-4 学习率、第二阶段世界模型学习率乘 0.25、KL 0.03、JEPA 1.25、free bits 0.2、前缀 horizon 3、衰减温度 1.5 和 seed 20260701。

差异记录如下。

- 使用公开 SafetyDrift 原始 285/72 划分作为训练/校准，按任务、动作、观测和标签去除 7 条完全重复记录，实际为 281 条训练（148 危险、133 安全）及 69 条校准（38 危险、31 安全）。ATBench 的 200 条既有留出集仅用于迁移测试，包括 101 条安全、99 条危险和 897 个候选动作。
- 字段按原始任务、此前一次观测、JSON 候选动作分别编码，采用 mean pooling，输入截断为 2048 token。当前动作的结果只用于世界模型训练目标，风险判定接口仅接收执行前字段。
- MLP 隐层为 512，残差适配器瓶颈为 256、缩放 0.25，动作和任务共用适配器；初始确定状态由任务表示经过可学习投影得到。推理使用 argmax 分类隐状态，训练使用 hard Gumbel straight-through。作者未公布完整投影、序列化、初始状态和推理采样实现。
- 论文附录 C.8 写明 Adam，本轮使用 AdamW、默认 weight decay 0.01、梯度裁剪 10。第二阶段固定 GRU 及输入 LayerNorm，学习两个风险头和其余相关路径。损失在整个 batch 的有效步上汇总，后继表示的中心化也使用所有有效步；这些实现细节无法与未公开的作者代码逐项核对。
- 原生 SafetyDrift 首次进入 risk_level=4 的动作提供危险步监督，危险步之后不计算安全损失；未执行论文描述的人工作者一致性审计。完全重复内容去重依据输入字段及首次危险位置，不等同于作者 B.3 的完整内容审计。
- HOLD/BLOCK 的安全校准误报预算设为 0.05/0.01，保留论文的 conformal 分位数公式。仅在校准集上搜索 4 个 beta、3 个窗口及自行选定的 3 组融合权重，共 36 组。该网格与最终阈值均记录到运行目录。测试标签仅用于最终指标统计。校准集只有 31 条安全轨迹，BLOCK 分位数被截至最大值，结合大于等于的触发规则，校准误报已为 1/31；这里的 1% 是名义预算，不能解释为已取得 1% FPR 保证。融合参数选择也复用了校准样本，未额外划分选择集。
- 文本编码时记录实际提取耗时，重复文本命中缓存计为零；之后单独逐步测量 recurrent head 延迟。两者相加作为缓存口径估计，未对每次在线调用从接收输入到最终决策重新计时，不能直接与论文端到端延迟比较。硬件为服务器单张 A100，论文使用 H100；本轮 PyTorch 为 2.5.1+cu124，Transformers 为 5.2.0。ATBench 缺少首个危险步标签，PHIR/MAS 留空。

论文原表未报告 ATBench，本轮结果应写为“DreamGuard 方法复现版在 ATBench 上的迁移测试”。 [论文实验配置](https://arxiv.org/html/2608.05695v1#S4.SS1) · [第三方项目自述](https://github.com/ioo0s/DreamGuard-reproduction)
