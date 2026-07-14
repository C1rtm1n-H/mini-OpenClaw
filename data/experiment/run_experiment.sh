#!/usr/bin/env bash
# ============================================================
# run_experiment.sh — 一键训练 + 评估脚本
# 用法：
#   bash run_experiment.sh                    # 使用默认参数
#   bash run_experiment.sh --epochs 50        # 自定义训练轮数
#   bash run_experiment.sh --help             # 查看所有参数
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo " Step 0: 安装依赖"
echo "========================================"
pip install -r requirements.txt --quiet

echo ""
echo "========================================"
echo " Step 1: 创建必要目录"
echo "========================================"
mkdir -p ./data/train ./data/test ./checkpoints

echo ""
echo "========================================"
echo " Step 2: 训练模型"
echo "========================================"
# 传递所有命令行参数给 train.py
python train.py "$@"

echo ""
echo "========================================"
echo " Step 3: 评估模型"
echo "========================================"
python evaluate.py --checkpoint ./checkpoints/model_final.pt

echo ""
echo "========================================"
echo " 实验完成！"
echo " 训练日志: 见上方输出"
echo " 模型:     ./checkpoints/model_final.pt"
echo " 评估结果: 见上方输出"
echo "========================================"
