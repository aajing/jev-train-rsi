# jev-train-rsi

本包将“小型 Qwen 基座＋合成数据＋训练优化”整理成 OpenRSI 提案。学生为 Qwen3-4B-Base，教师为官方 Qwen3.8-27B，在单 H100 上分时运行。任务直接生成答案，可选推理过程，最终标签由七类固定程序规则验证。

默认研究预算 24 小时，可另行记录延长至 48 小时。每候选最多 2 万条训练状态、200 万教师 token、2000 万学生训练 token、2 小时计费生产时间，Judge 另限 30 分钟。目标每轮完整周期约 2 小时，实际耗时仍需验证。满分要求候选合规且 2800 道隐藏题全部正确。

## 提交文件

- [proposal.md](proposal.md)：可作为 Discussion 正文的英文官方 28 字段单表。
- [SUBMISSION.md](SUBMISSION.md)：标题、公开附件范围、提交路径与贡献者资料。
- [DATA_SPEC.md](DATA_SPEC.md)：中文数据、修改范围、分层配额和计费合同。
- [RUNBOOK.md](RUNBOOK.md)：CPU 检查与后续模型运行集成边界。
- `dist/jev-train-rsi-submission.zip`：可公开技术附件，排除隐藏题及私有 seed。

贡献者资料已填写为 Jing Qiu、ajing@autotrust.ai；相关项目证据采用贡献者指定的 AutoTrust GitHub 和 Hugging Face 公开链接。公开仓库：`https://github.com/aajing/jev-train-rsi`；官方提案：https://github.com/OpenRSI-Foundation/OpenRSI-Index/discussions/148。

## 已完成的优化

- Judge 按答案与边界情况分层，七领域 × 两条件 × 200 题，共 2800 题。
- 严格 CPU 评分要求冻结数据哈希、完整题目/响应 ID 集及每组数量全部匹配。
- B1 固定语料、随机状态、顺序和配置；20000 条语料可逐字重建。
- 教师提供“程序生成＋难例解释”的参考策略，Agent 保留方法选择权。
- 缓存成本按唯一 receipt 及祖先计费，候选额度与轨迹实际时间分开计算。

## 数据与证据

| 资产 | 数量与用途 |
| --- | --- |
| `data/public/train.jsonl` | 1800 条免费启动种子 |
| `data/public/development.jsonl` | 209 条开发诊断题，不用于梯度训练 |
| `data/public/reference.jsonl` | 477 条公开参考题，不用于训练或正式评分 |
| `data/baseline/` | 20000 条固定 B1 参考语料及 provenance；正式使用须计费 |
| `data/private/` | 2800 条隐藏 Judge 与私有 seed；禁止公开或挂载到 Work |
| `configs/` | 基线、教师参考配置、预算数值与公式 |
| `evidence/`、`data_manifest.json` | CPU 重建、完整性和分层审计 |

35 项 CPU 测试与重建检查已通过，另已用本次 2800 题验证全对、错一题、缺失响应的评分边界，汇总见 `evidence/submission_checks.json`。这些是协议测试；模型尚未训练，baseline 没有分数，H100 时间与显存未实测。严格 CPU 评分和预算算术不能替代可信 GPU 运行、模型来源核验与在线预算执行。Harbor 集成的剩余部分见 RUNBOOK。JEV-27B 仅是研究动机，合成教师明确为官方 Qwen3.8-27B。
