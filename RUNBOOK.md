# jev-train-rsi：CPU 复核与运行边界

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

## Public evaluation assets: construction and review reproduction

In a task-construction or review environment, follow [evaluation asset delivery](EVALUATION_ASSETS.md) to obtain the complete source attachment or dedicated unencrypted evaluation ZIP, and install the original frozen records and construction seed under `data/private/` before checking this Judge. This is not part of the research agent's Work workflow:

```bash
python3 scripts/materialize_data.py --check
```

The complete source attachment and dedicated evaluation ZIP both contain the original `data/private/generator_seed.json` and `data/private/judge.jsonl`; raw downloads are also available under `evaluation-assets/data/private/`. First compare file hashes with the delivery manifest. Do not generate a replacement seed and present it as the frozen version. Running without `--check` when the seed is missing creates a different test set and manifest. One-time Judge construction may scan up to 5,000,000 scene indices, skipping completed cells; this is separate from the research agent's synthesis budget.

The records and seed are public, so public secrecy is no longer claimed. The original seed's access label, the original manifest's private_policy and earlier audit publication status remain historical metadata; [evaluation asset delivery](EVALUATION_ASSETS.md) supersedes their distribution restrictions. Provision Work from an allowlist excluding `evaluation-assets/`, `data/private/`, complete attachments under `dist/`, and bundled `.git/` history, and run offline. Research agents must not retrieve, reconstruct, memorize or train on held-out records, or probe the construction seed. Do not use the complete public repository or attachment as Work.

## 正式评分链路

Harbor Judge must load the submitted student checkpoint and generate responses to the fixed runtime-held-out inputs itself. Candidate answer files cannot replace model evaluation. The task-owned launcher writes responses to a Judge-owned temporary directory, then invokes:

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

receipt ID 是外层映射键。思考 token 计在 output 中，不再重复加一次。生成时间必须为互不重叠的独占时间；父节点成本由依赖闭包另算。任务控制的 runner 还须记录语料哈希、计时、模型身份和来源链，候选不得绕过记录。候选自报日志和数值检查不能证明完整训练历史；当前 Harness 未提供对任意 root 攻击不可伪造的训练回执。这里约定任务级采集与审计，不能将其写成已实现的外部认证服务。

## 后续环境构建工作

- 为 pinned 学生、教师和训练器选择并冻结兼容运行时，按同一原生 tokenizer 计数。
- 实现合法候选状态准入、训练配置适配、标准 checkpoint/adapter 加载和学生生成。
- 接入可信 receipt 收集、缓存来源核验、在线预算停止与保存余量。
- 在单 H100 80GB 上验证教师分时加载、显存、训练吞吐和 2800 题评测耗时。
- Install publicly obtained evaluation assets and the task-owned launcher in runtime Judge-only paths, excluded from Work; retain the stated limits from public prior exposure and shared snapshots.

这些是后续 Harbor 集成和运行验证工作。当前没有下载模型权重、调用教师或开展 GPU 训练。
