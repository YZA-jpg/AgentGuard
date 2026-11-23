# ATBench Pro 原始JSON判别补测

**目标：** 新增一行Pro普通零样本检测，与现有作者模板组并列；同一heldout200（99危险/101安全），不替换旧分数。

**输入：** 保留原始`contents`嵌套轮次与role/content/thought/action；工具保留name/description/parameters，与作者模板组的信息范围一致。不输入id、label、reason、risk_source、failure_mode、real_world_harm及工具来源元数据。原始整行含答案，不能直接作为提示。

**提示：** 独立简短通用安全分类说明，不导入AgentDoG提示、不使用作者四项分析要求、不调用专用护栏。输出一个JSON对象label=safe/unsafe和简短reason。原始数据内指令视作待审证据。

**参数：** deepseek-v4-pro；temperature0、enable_thinking=false、max_tokens1024；不指定top_p或seed；OpenAI兼容接口、timeout180秒、SDK max_retries1；默认4线程、每线程独立客户端。无GPU、不截断输入。记录请求参数、响应模型/finish_reason/token用量、输入哈希、原始输出和耗时，不记录密钥。

**步骤：**

1. 在`tests/test_atbench_pro_raw.py`验证答案字段排除、嵌套内容不变、严格输出解析、API参数和独立重算。
2. 新增独立入口`agentguard.atbench_pro_raw`，不修改现有运行中的SafePred或原作者模板入口。
3. 新增`run-atbench-pro-raw.sh`：先2条calibration smoke，通过格式/覆盖/模型响应记录验收后，自动运行heldout200并核验。
4. 本地与服务器CPU测试；代码先本地编写、同步至data1并备份GitHub。提供可复制的tmux启动命令和结果路径，按用户约定由用户启动，不自动启动正式200条。
5. 主表新增“Pro零样本安全判别（通用提示＋原始JSON）”，正式运行完成前保持空值。汇总F1、Recall、FPR、平均审核秒数、错误数、token用量和并发数。

**比较边界：** 本组同时改提示、轨迹序列化和输出格式，不宣称是只替换提示的单变量消融；骨干、200条ID、工具信息范围和采样/输出预算保持不变。旧简化512输出且无工具组不代替本组。
