# CPU 复核与运行边界

本包实现了数据构建、固定 B1 语料、答案协议、严格 CPU 评分和预算算术。它不是已验证的 Harbor 运行环境，也没有模型成绩。

## 公开附件可运行的检查

在包的根目录使用 Python 3，所需 CPU 代码仅用标准库，无需下载模型或使用 GPU：

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/build_baseline.py --check
```

测试覆盖答案格式与类型、七领域标签转换、基线随机状态和尝试计数、完整 2800 题评分、缺失或重复 ID、数据哈希、缓存祖先计费与重复计费。

B1 参考语料为 20000 条，包含 1800 条原始种子及 18200 条新增 ID 场景；固定构建共使用 24125 次 proposal。参考哈希为：

```text
e3dcaf05a4bc8ae0e2f67f9af62185be63b31ba762699e4083123eff5e575ffb
```

正式 B1 必须重建并计费，或继承可信首次构建成本。这里验证的是配方和语料重放，不是模型权重重放。

## 出题方本地私有检查

只有持有原私有 seed 的出题方才能逐字重建本次 Judge：

```bash
python3 scripts/materialize_data.py --check
```

公开 ZIP 故意不包含 `data/private/generator_seed.json`，因此不能用它复现这份隐藏测试。缺少 seed 时运行非 `--check` 模式会创建另一份测试集和新的 manifest，不能将其冒充为本次冻结版本。Judge 一次性构建允许最多扫描 5000000 个场景索引，使用跳过已满组的优化；这与解题 Agent 的训练合成预算无关。

## 正式评分链路

Harbor Judge 需要自行加载提交的学生 checkpoint，并对固定隐藏输入生成响应；候选不能直接交答案文件代替模型。可信启动器将响应写入 Judge 自有临时目录，然后调用：

```bash
python3 scripts/judge_gate.py \
  --dataset /task-owned/judge.jsonl \
  --manifest /task-owned/data_manifest.json \
  --responses /task-owned/run/responses.jsonl \
  --manifest-sha256 <trusted-manifest-sha256>
```

这些路径和哈希由可信启动器提供，不接收候选自带的 manifest 来授权其自带答案。响应 JSONL 每行严格为 `{"id":"...","response":"..."}`。

入口核验冻结文件哈希、2800 个唯一题目 ID、14 组各 200 题及响应的完整一一对应，然后计算分数。单题空字符串代表完成生成但答案缺失，计错；缺少整条响应记录代表评测未完成，拒绝评分。

纯 CPU 分数仍返回 `eligibility_checked=false` 和 `response_provenance_verified=false`。它不证明 checkpoint 来源、GPU 执行、预算或修改范围合规；这些必须由外层 Judge 验证。合规满分需要完整正确的 2800 题及全部外层检查通过。

## 预算接口

`configs/budget.json` 是固定数值与公式，`scripts/budget_accounting.py:account_candidate` 是可测试算术函数。它接收可信 runner 采集的本次实际 Work 时间、样本/token 计数、全部当前 receipt 和复用语料 receipt。

每条 receipt 的最小计费字段为：

```json
{
  "origin_candidate_id": "candidate-001",
  "parent_ids": [],
  "generation_seconds": 20,
  "proposed_states": 3,
  "teacher_input_tokens": 10,
  "teacher_output_tokens": 5
}
```

receipt ID 是外层映射键。思考 token 计在 output 中，不再重复加一次。生成时间必须为互不重叠的独占时间；父节点成本由依赖闭包另算。可信 runner 还须记录语料哈希、真实计时、模型身份和不可由候选伪造的来源证明。数值检查通过不能替代这些证明。

## 后续环境构建工作

- 为 pinned 学生、教师和训练器选择并冻结兼容运行时，按同一原生 tokenizer 计数。
- 实现合法候选状态准入、训练配置适配、标准 checkpoint/adapter 加载和学生生成。
- 接入可信 receipt 收集、缓存来源核验、在线预算停止与保存余量。
- 在单 H100 80GB 上验证教师分时加载、显存、训练吞吐和 2800 题评测耗时。
- 将 Judge 数据与可信启动器放入正确的 task-owned 私有路径，保留共享快照环境的已知限制。

这些是后续 Harbor 集成和运行验证工作。当前没有下载模型权重、调用教师或开展 GPU 训练。
