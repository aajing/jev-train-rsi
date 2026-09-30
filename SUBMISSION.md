# OpenRSI 提交说明

提交正文是本目录的 [proposal.md](proposal.md)。它使用官方英文单表模板，保留全部 28 个字段及顺序，技术选择已经写入正文；中文解释和实现证据放在附件中。

建议 Discussion 标题：

```text
Fixed Budget Synthetic Data and Training Optimization for Qwen Decision Reasoning
```

## 贡献者资料

以下资料由贡献者提供，相关公开项目按其指定采用 AutoTrust：

| 正文字段 | 已填写内容 |
| --- | --- |
| Contributor — Full name | Jing Qiu |
| Contributor — Email | ajing@autotrust.ai |
| Research Question — Repository URL 中的 contributor evidence | [AutoTrust 训练优化项目](https://github.com/AutoTrustAI/autoresearch-sota-strategy)、[JEV-27B 模型](https://huggingface.co/autotrust/JEV-27B)，以及 [GitHub 组织](https://github.com/AutoTrustAI)和 [Hugging Face 组织](https://huggingface.co/autotrust)主页 |

此前保留的姓名、邮箱和项目链接 TODO 已补齐。正文以 AutoTrust 为贡献者选择的研究背景与相关工作证据，并保留实际依赖的 Open-Jev 数据生成器及 LLaMA-Factory 来源。AutoTrust GitHub 项目的固定提交与参考文件已列入正文。

## 提交内容

1. 正文：使用完整的 `proposal.md`，保留单表结构。
2. 技术附件：`dist/qwen-rsi-submission.zip`，包含正文、中文规范、配置、公开数据、B1 参考语料、CPU 代码及审计结果。
3. 私有出题材料：`data/private/` 留在本地；在后续官方私有任务构建环节交付，不随公开 Discussion 或附件发布。

公开附件不包含隐藏测试题、私有 seed、模型权重或凭据。附件内的 Judge manifest 仅公开聚合设计和文件承诺，不包含逐题指纹。B1 语料虽然可以公开审核，但正式研究时仍需在 Work 重建计费或继承可信构建成本。

## 官方提交路径

在官方 [OpenRSI-Index 仓库](https://github.com/OpenRSI-Foundation/OpenRSI-Index) 的原生 Codex 或 Claude Code 会话中，使用 `proposal-agent` 提交最终正文，并保留该会话处理反馈。官方工具负责创建和更新 Task Ideas Discussion。具体步骤以[贡献页面](https://index.openrsi.foundation/contribute)及[官方提交工作流](https://github.com/OpenRSI-Foundation/OpenRSI-Index/blob/main/.agents/skills/proposal-agent/references/discussion-lifecycle.md)为准。

本目录仅完成材料准备，没有发布 Discussion、运行 GPU 训练或创建云端资源。修改正文后，在根目录运行 `python3 scripts/package_submission.py` 重新生成公开附件及 SHA256 校验文件，避免两份版本不一致。

## 审核者阅读顺序

- `proposal.md`：研究问题、修改边界、评分和预算的完整技术定义。
- `DATA_SPEC.md`：七领域支持范围、分层配额、教师策略、计费公式和满分规则。
- `RUNBOOK.md`：可执行 CPU 检查及尚需 Harbor 集成的部分。
- `configs/`：固定基线、教师参考设置和预算数值。
- `evidence/`、`data_manifest.json`：重建和完整性证据；不代表模型成绩。

正式提交是否通过取决于官方审核，尤其包括贡献者领域经验。官方提案阶段不要求已经复现 baseline 或完成完整 GPU 实验，环境构建和实际轨迹在后续完成。[官方模板](https://github.com/OpenRSI-Foundation/OpenRSI-Index/blob/main/.agents/skills/proposal-agent/references/proposal-template.md)
