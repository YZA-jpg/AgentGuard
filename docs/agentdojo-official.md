# AgentDojo 官方流程与 Flash 复测

2026-11-20：AgentDojo 新实验统一使用 `python -m agentguard.native_agentdojo`。入口、环境和协议与历史 IPIGuard 适配分开。模型为 `deepseek-v4-flash-0731`，无外接护栏，系统提示没有额外防注入指令。

## 作者资产与覆盖

- 官方 AgentDojo 0.1.35，benchmark v1.2.2；Git 标签提交 `a75aba7631d3ca5fb7ab938965c97ead2f9ff84b`。
- 官方 wheel SHA256：`364bea4219716b716bf639f504d195943f7f6a5535d312ca41d7098704a2affd`。
- 112 个包内文件与标签源码逐字节一致，哈希固定在 `configs/agentdojo-official-v0.1.35.json`，每次启动重新校验。系统提示、工具、数据、执行循环、注入位置选择、攻击模板和 checker 均直接调用未修改的作者代码。
- 正式环境：`/data1/yaoziao/agentguard/.venv-agentdojo-author`，不继承系统 site-packages。原仓库 `uv.lock` 经 `uv export --frozen --no-dev --no-emit-project` 导出为带哈希的 `requirements-native-dojo-author.txt`，另加已核对的官方 wheel，63 个依赖均按哈希安装。核心版本包括 OpenAI SDK 1.76.2、Pydantic 2.11.4；启动时检查依赖版本与导出文件哈希。Python 3.10.21 仅提供解释器，未导入旧 IPIGuard 包或评测辅助函数。

| Suite | 良性任务 | 攻击目标能力检查 | 正式攻击用例 |
|---|---:|---:|---:|
| Workspace | 40 | 14 | 560 |
| Slack | 21 | 5 | 105 |
| Travel | 20 | 7 | 140 |
| Banking | 16 | 9 | 144 |
| 合计 | **97** | **35** | **949** |

按良性 → 能力检查 → 攻击三个阶段顺序执行，各阶段 4 个独立进程并发调用 API；不占 GPU。能力检查直接将作者注入任务的 GOAL 当作用户任务，记录其可完成性，与作者 benchmark 的前置步骤一致，不混入攻击 ASR。能力检查失败只反映模型表现，不删除对应攻击目标。Workspace 25 在原生实现中可正常找到注入位置，因此保留；旧组 96/935 的排除项不再沿用。

## 配置与必要适配

| 项目 | 本轮配置及与作者发布代码的关系 |
|---|---|
| 流程 | 作者 `AgentPipeline.from_config(defense=None)`，原始默认提示，YAML 工具返回，原始 15 次工具循环及最多 3 次无最终输出重试。 |
| 模型/API | Flash-0731 替换原论文 backbone；调用现有 OpenAI-compatible 服务。每次保留实际响应模型 ID，此 ID 本身不证明服务端权重永不变化。 |
| 温度 | 显式传入 `0.0`；作者适配器会把默认 0 因 falsy 判断而省略。本轮修正这个请求层行为，并明确记录。 |
| 思考/输出上限 | 与作者请求方式相同，不显式传 `enable_thinking`、`reasoning_effort`、输出 token 上限、top_p 或 seed。服务端生效默认值未知；不把“未指定”写成“已关闭”。 |
| 系统角色 | SDK 中作者使用 `developer`，请求兼容层映射为 `system`；提示文本不变。 |
| 攻击 | 仅作者 `important_instructions` 实现。为作者未收录的模型 ID 增加显示名 `DeepSeek`；未改模板、目标文本或注入候选生成。 |
| 推理内容 | 保存完整响应；若服务返回工具调用推理字段，后续请求回传 `reasoning_content` 以兼容服务协议，不将其添加为系统指令。 |
| 错误 | 保留原生判分和错误标志；单个用例最多 2 次独立尝试，全部保留，只按运行有效性重试，不按任务成败重试。作者 SDK 调用重试最多 3 次、SDK 内部最多 2 次，配置均记录。 |
| 并发 | 4 个进程，各自持有环境、客户端及作者 logger。与原 CLI 串行顺序不同；整批时长和调用延迟受并发影响。 |

这是官方 benchmark 协议在 Flash 上的重新评测，不是原论文旧 backbone、多种攻击策略全部结果的数值复刻。历史护栏结果仍属于旧框架；后续护栏应迁入同一原生框架后再作公平对比。

## 已验收与当前正式批次

作者依赖锁环境的小规模目录：`/data1/yaoziao/agentguard/results/agentdojo-official-author-flash-smoke-20261120_201354`。

9 项离线测试通过。12 条验收用例（每 suite、每阶段 1 条）全部完成，运行错误 0、重试 0；34 次 API 调用均返回 `deepseek-v4-flash-0731`。独立离线复核确认原始系统/用户提示、工具 schema、攻击字典及 checker 判分一致，4 条攻击的注入均实际进入模型请求。良性 Utility 3/4、能力检查完成 4/4、攻击 ASR 0/4，均仅用于验收，不能当作正式成绩。

作者依赖锁正式批次已于 2026-11-20 20:15（北京时间）按用户此前授权启动，用户随后明确要求继续运行：

`/data1/yaoziao/agentguard/results/agentdojo-official-author-flash-20261120_201550`

共 1081 条，四进程。最终分数以批次完成并通过独立复核后的汇总为准。

中间批次 `agentdojo-official-flash-20261120_153500` 使用相同作者源码，但依赖为按公开范围解析的较新版本（74 个，SDK 3.57.0 / Pydantic 2.14.4）。它已完整完成并独立验收：正常 Utility 89/97（91.75%）、能力检查 30/35（85.71%）、攻击 ASR 3/949（0.316%）、攻击 Utility 836/949（88.09%），运行错误 0。保留为现代依赖对照，不与作者锁定依赖正式组混记；其源码版本为 Git `9c19a75`，环境与版本快照仍保留。

## 保存内容与统计

- `plan.json`：冻结模型、参数、源码/依赖/提示/schema 哈希和全部用例 ID；`run_metadata.json` 保存环境、来源和实际请求配置，密钥不入日志。
- `cases.jsonl`：已完成用例的最终记录，包含 `stage`、任务 ID、注入、原生轨迹、判分、模型 ID 和各原始文件路径。良性、能力检查、攻击通过 `stage` 区分。
- `attempts.jsonl`：所有已收集尝试，包括失败与成功重试；每个尝试各有 `attempts/<case-key>/<attempt>/case.json`。
- 每个尝试目录的 `native/` 保存作者格式的 trace JSON，`api.jsonl` 保存 SDK 调用层的完整请求、响应、推理字段、token 统计、模型 ID、耗时和错误码。SDK 内部 HTTP 重试没有单独响应记录，其等待时间包含在 SDK 调用耗时中。
- 作者在没有最终输出时可能重启查询，原生 trace 仅保留最后一段；完整 API 请求/响应同时保存前面查询。离线复核从完整请求历史恢复已执行动作，保留原生 checker 对最终查询调用栈的语义，单列发生重启的任务。
- `summary.json`：实时进度，分阶段 ASR、Utility、有效/错误/未运行数量，全部已收集尝试的 token 统计。当前 ASR 分母为已完成的有效攻击用例，不包含待运行或错误用例，完成前不能与全量分数比较。
- 本组无外接分类护栏、无独立动作安全标签，F1/Recall/FPR/审核 Latency 为 null。整条任务耗时和 SDK 调用耗时另记，不能填作护栏审核耗时。
- `batch.done` 表示全部用例运行有效；`verification.json`、`verified.done` 表示独立离线复核通过；`batch.exit=0` 表示启动脚本与复核均成功。需同时核对这些文件。

## 运行与查看

首次配置：

```bash
cd /data1/yaoziao/agentguard
bash scripts/setup-official-dojo.sh
.venv-agentdojo-author/bin/python -m unittest tests.test_native_agentdojo -v
.venv-agentdojo-author/bin/python -m agentguard.native_agentdojo inspect
```

凭据位于 AgentGuard 自己的 `.env`，包含 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。本轮从既有配置无回显复制；后续换 key 在这个文件更新。该文件被 Git 忽略。

当前批次监控：

```bash
tmux -S /data1/yaoziao/agentguard/cache/tmux/agentdojo-official.sock attach -t flash_author
tmux -S /data1/yaoziao/agentguard/cache/tmux/agentdojo-official.sock capture-pane -p -t flash_author:run -S -20
```

从 attach 界面按 `Ctrl+b` 再按 `d` 返回终端，后台继续执行。正式任务已启动，不需要重复启动。

完成后手动复核，或在同一协议下恢复缺失/错误用例：

```bash
run=$(cat /data1/yaoziao/agentguard/results/agentdojo-official-flash-latest.txt)
cat "$run/summary.json"
.venv-agentdojo-author/bin/python scripts/verify-official-dojo.py "$run"
# 仅在已有任务停止且需要补测时执行：
bash scripts/run-official-flash.sh "$run" --resume
```

更换模型时使用新结果目录和 `--model`、`--attack-model-name`；可通过 `--stage benign` / `--stage capability` / `--stage under_attack`、`--suite` 选择范围，通过 `--limit-per-suite 1` 验收。参数、源码或依赖改变时禁止续写旧批次。`scripts/run-official-flash.sh` 是本轮固定 Flash 配置的启动器。

用户于 2026-11-20 更新运行约定：当前批次继续，后续默认提供启动命令，由用户执行；不主动监视或等待任务结束。默认可并发，不适合时说明串行原因。原始依赖范围解析得到的 `requirements-native-dojo.txt` 仅用于历史对照，正式环境使用带哈希的作者导出文件。
