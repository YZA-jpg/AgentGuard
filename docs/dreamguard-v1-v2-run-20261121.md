# DreamGuard v1 / v2 对比批次

用户于 2026-11-21 明确授权代为启动两版训练与比较。

运行目录：`/data1/yaoziao/agentguard/results/dreamguard-v1-v2-20261121_015401`。

源码快照：v1=`526257e`，v2=`629584c`，分别冻结于 `vendor/dreamguard-comparison-snapshots/v1` 和 `v2`；快照逐文件字节与 Git blob 核对。训练代码没有为本次比较改写，当前主工程的后续改动不会混入此批次。

| 项目 | v1 | v2 |
| --- | --- | --- |
| 世界模型/风险训练 | 新训练，10/12 epoch | 新训练，10/12 epoch |
| 训练/校准/独立测试 | 281 / 69 / 无独立 SafetyDrift 测试 | 221 / 57 / 72 |
| 冻结特征 | 复用已校验的历史特征 | 新提取，编码 batch 8 |
| 历史权重 | 不复用 | 不复用 |
| 原生 ATBench 范围 | 200 留出 | 1000 全量 |
| 最终配对比较 | 相同的 200 条，99 危险、101 安全 | 相同的 200 条，99 危险、101 安全 |
| 配对延迟 | 关闭文本缓存，保留 v1 原生 FP32 mean pooling 与动作格式 | 关闭文本缓存，保留 v2 原生 BF16 masked mean pooling 与动作格式 |

v1 的特征复用检查包括：原特征生成代码、Qwen revision、输入文本/标签/划分联合哈希、ATBench 数据哈希、split 文件哈希、特征形状与 ID 顺序。复用特征节省重复编码成本，不代表复用训练完成的模型；来源记录在 `v1-feature-provenance.json`。

使用同一张 GPU 3（A100 80GB）串行运行。启动前约 33GB 可用，已有 vLLM 进程保留；不停止或更改其他任务。共享服务器负载可能变化，`gpu-*.txt` 保存各阶段资源状态，配对延迟不能当成独占 GPU 的硬件结论。

## 执行顺序和输出

1. v1 重新训练、校准，生成 `v1/atbench.jsonl`。
2. v2 重新提取特征、训练、校准，生成 `v2/safetydrift-native.jsonl`，再生成 `v2/atbench-native.jsonl`。
3. 加载两版新权重，各自在共同 200 条上重新执行因果审核，生成 `paired-v1.jsonl`、`paired-v2.jsonl`。统一从执行前文本输入到最终决策计时，首步任务编码计入；有一次模型预热，模型加载不计入每次延迟。
4. 自动生成 `comparison.md`、`comparison.json`：F1、Recall、FPR、延迟均值，JSON 另含中位数、P95、混淆矩阵、两版差值及原生评测与复测的预测变化数。v2 全量 1000 与 SafetyDrift72 独立列出。

ATBench 没有可靠的首个危险步及恢复标签，PHIR/MAS/recovery FPR 留空。v1 的 SafetyDrift 69 条用于校准，不能作为独立测试与 v2 的 72 条比较。两版同时改变了划分、损失归一化、优化器及输入细节，本实验属于整体版本对比，不是单因素消融。

失败会记录到 `status.json` 的 `failed_phase`，不会生成成功的最终比较；不要把部分输出当成全量结果。源快照校验与比较器的 5 项 CPU 测试已通过。训练结果应以实际落盘输出为准。

## 查看命令

```bash
cd /data1/yaoziao/agentguard
run=results/dreamguard-v1-v2-20261121_015401
cat "$run/status.json"
tail -n 30 "$run/controller.log"

tmux -S /data1/yaoziao/agentguard/cache/tmux/dreamguard-comparison.sock attach -t dreamguard_compare
# Ctrl+b，松开，再按 d：离开会话而不停止任务。

# 完成后读取自动生成的对比表
cat "$run/comparison.md"
```

此批次启动后不需要再手动启动 v1、v2 或比较脚本。启动器为 `scripts/run-dreamguard-comparison.sh`，控制器为同名 `.py`。
