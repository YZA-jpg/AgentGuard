# 按 deepseek_result 已知配置复测 Pro

参考目录：`/data1/yaoziao/agentguard/deepseek_result`。原始 939 条，官方 ASR 425/939（45.26%），攻击环境 Utility 609/939（64.86%）。用户确认没有原始启动参数，因此只对齐日志可验证的配置；缺失的采样设置沿用服务默认。

## 本轮配置

| 项目 | 配置 |
|---|---|
| 任务代理 | `deepseek-v4-pro` |
| 作者版本 | AgentDojo 0.1.35，benchmark v1.2.2，原始 uv.lock，`.venv-agentdojo-author` |
| 系统提示 | 作者原始无防御提示；与参考 939 条逐字匹配 |
| 攻击 | 作者 `important_instructions`，显示名精确设为 `Deepseek v4 Pro` |
| 攻击字典 | 按作者代码生成，与原始 939 条的注入字典全部相同；每次启动先离线重核 |
| 用例范围 | Workspace 560、Slack 95、Travel 140、Banking 144；保留 Workspace 25，排除参考未测试的 Slack 用户任务 7 和 17 |
| 初始用户指令 | 939 条全部与作者原文一致 |
| 温度 | `--temperature provider`：请求完全省略 temperature，不发送 0 或 null |
| 思考、输出上限 | `--thinking provider`，不显式指定 enable_thinking、reasoning_effort、输出 token 上限、top_p、seed；生效默认值未知 |
| API | AgentGuard `.env` 中当前服务。历史记录没有地址和实际模型快照，不能声称与当时服务完全相同 |
| 并发 | 默认 4 个独立 API 进程，无 GPU 需求；可在启动前设置 `PRO_REFERENCE_WORKERS` |

一次启动依次执行：离线参考输入比对 → 8 条小规模验收并复核 → 35 条能力检查 → 939 条攻击 → 完整离线复核。正式组为 974 条，ASR 分母仅使用其中的 939 条攻击；小规模记录单独保存。不依据任务/攻击是否成功来重试，只处理运行错误。

已通过 11 项离线测试和全部参考输入核对，开发阶段没有调用真实 Pro API。原 Banking `(1,0)` 日志在初始用户消息之外有 4 条监控反馈，本轮使用作者初始指令，不插入这些历史反馈；该差异写入参考报告。历史 endpoint、采样设置、服务端快照、依赖锁不完整，45.26% 是参考结果，不是本轮必须达到的目标。

与此前 Flash 正式组相比，本轮温度改为省略、显示名与任务范围也对齐外部 Pro。因此它是外部结果的已知配置复测，不能直接当成只替换 backbone 的单因素实验。

## 用户启动命令

```bash
cd /data1/yaoziao/agentguard
stamp=$(TZ=Asia/Shanghai date +%Y%m%d_%H%M%S)
out="/data1/yaoziao/agentguard/results/agentdojo-pro-reference-${stamp}"
sock=/data1/yaoziao/agentguard/cache/tmux/agentdojo-pro-reference.sock
mkdir -p /data1/yaoziao/agentguard/cache/tmux

tmux -S "$sock" new-session -d -s pro_reference -n run \
  "bash /data1/yaoziao/agentguard/scripts/run-reference-pro.sh '$out'"
tmux -S "$sock" set-window-option -t pro_reference:run remain-on-exit on
```

上述命令由用户执行；助手不自动启动或等待这个批次。

```bash
tmux -S /data1/yaoziao/agentguard/cache/tmux/agentdojo-pro-reference.sock attach -t pro_reference
```

按 `Ctrl+b` 再按 `d` 返回终端。结果目录显示在日志中，也可从 tmux 面板读取。`$out.reference.json` 保存原始文件哈希、匹配情况、原始分数及未知配置；`$out-smoke` 为验收数据，`$out` 为正式数据。

正式目录中，`cases.jsonl`、`attempts.jsonl`、逐次 `api.jsonl`、原生 trace、`summary.json` 和 `verification.json` 与 Flash 流程相同。`batch.done`、`verified.done` 及 `batch.exit=0` 同时存在才代表全批次有效且已复核。阶段内统计不混入能力检查。

若 API 路由不支持 Pro，小规模阶段会保留错误并停止。修正问题后使用新时间戳，或在相同代码和配置下通过 `bash scripts/run-reference-pro.sh 原结果目录 --resume` 补测。不要同时对同一结果目录发起两次运行；已有 tmux 会话需使用新的会话名。

## 版本与历史结果

本次新增可选温度省略和用例排除功能，不修改作者包或默认 Flash 温度 0 行为。源码哈希变化意味着旧批次的严格复核/恢复要使用其冻结源码版本，不能绕过哈希检查：Flash 作者锁定依赖批次见 `source_backup.json`，对应 Git `c9a4536`。旧结果与验收文件不改写。
