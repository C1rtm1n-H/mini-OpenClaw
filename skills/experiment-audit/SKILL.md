---
name: experiment-audit
description: 当用户需要审查实验代码的可复现性、正确性和完整性时使用（不真正运行完整实验），适用于论文复现前摸底、选基线技术评估、审稿、代码交接场景。
---

# 实验代码只读审计

目标是在完全不执行、不导入、不修改被审仓库的前提下，判断论文实验能否复现，并为每个结论给出可人工核对的文件和行号。

## 1. 定位入口与文档

1. 用 `glob` 扫描 README、论文或说明文档、`*.py`、`*.sh`、配置、依赖和环境文件。
2. 用 `grep` 搜索 `argparse|click|hydra|if __name__|main\(`，再用 `read` 确认训练、评估、推理入口，禁止执行入口文件。
3. 从 README 提取示例命令；从源码静态提取参数名、默认值、required、类型和配置覆盖规则。
4. 输出“README 命令 vs 代码参数”对照表，逐项标记一致、不一致或未验证，并附双方证据位置。

## 2. 检查可复现性

用 `grep` 缩小范围，再用 `read` 复核完整上下文：

| 检查项 | 搜索线索 | 判定重点 |
|---|---|---|
| 随机性 | `seed|random|deterministic|cudnn` | Python、NumPy、PyTorch、CUDA 和数据划分是否全部固定 |
| 数据划分 | `split|shuffle|sampler|fold` | 划分来源、seed、测试集泄漏和划分文件是否固定 |
| 依赖 | `requirements|environment|pyproject|import` | Python/CUDA/框架版本是否明确，import 是否有声明 |
| 路径 | `/home/|/data/|/mnt/|[A-Za-z]:\\|output` | 数据、checkpoint、缓存和输出目录是否硬编码 |
| 指标 | `accuracy|f1|bleu|rouge|precision|recall|mse|mae` | 公式、阈值、平均方式、聚合和论文/README 是否一致 |
| 资源 | `cuda|gpu|device|batch_size|num_workers` | 设备是否可配置，资源需求是否有代码或文档证据 |

没有论文或论文未声明某项时写“未验证”，禁止推断一致。

## 3. 静态危险副作用扫描

1. 必须先调用 `audit_scan` 扫描所有 Shell/Python 入口。
2. 用 `read` 复核每个删除、覆盖、下载、安装、`subprocess`、`os.system` 命中项。
3. `rm -rf outputs`、`shutil.rmtree`、覆盖 checkpoint、下载数据和自动安装依赖都必须单独列入报告。
4. 不执行 `train.sh`、`train.py --help`、`import train`、Notebook 或任何项目脚本；`--help` 和 import 也可能触发顶层副作用。

## 4. 输出报告

报告直接作为最终回答输出，不调用 `write`，固定包含：

1. 审计范围与只读声明。
2. 训练/评估/推理入口及证据。
3. README 命令与代码参数对照表。
4. 数据路径、依赖、随机种子、数据划分、确定性和资源配置。
5. 指标与论文/README 一致性证据。
6. 危险副作用扫描结果。
7. 问题表：固定 ID、严重性、Confirmed/Suspected/Unverified、文件:行号、影响和修复建议。
8. 总结判定：可复现、有条件可复现或暂不可复现。
9. 未验证项和建议的轻量验证命令；这些命令只作为建议，不在审计过程中执行。

## 强制边界

- 只使用 `glob`、`grep`、`read`、`audit_scan`。
- 不修改文件，不写报告到仓库，不安装依赖，不下载数据或模型。
- 不执行训练、推理、评估、数据处理及任何未知脚本。
- 用户要求完整训练时明确拒绝实际执行，改为静态审计、轻量验证建议和分阶段复现计划。
- 资源、耗时和显存没有文档或配置证据时写“无法从静态证据确认”，不编造估计。
