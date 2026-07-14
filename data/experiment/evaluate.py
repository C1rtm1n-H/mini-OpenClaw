"""评估脚本 —— MiniImageNet Few-Shot Baseline.

修复记录（对应审计报告缺陷）：
  D9: 已修复 —— 按 batch 大小加权平均准确率
  D10: 已修复 —— scikit-learn 已在 requirements.txt 中声明
  D11: 已修复 —— 添加 model.eval() 和 torch.no_grad()
"""

import argparse
import torch
from sklearn.metrics import accuracy_score
from train import ConvNet, MiniImageNetDataset
from torch.utils.data import DataLoader


def evaluate(checkpoint_path: str, data_dir: str, batch_size: int, device: str):
    model = ConvNet()
    checkpoint = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(device)
    model.eval()  # D11: 切换到评估模式

    dataset = MiniImageNetDataset(data_dir, split="test")
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=False)

    total_correct = 0
    total_samples = 0
    with torch.no_grad():  # D11: 禁用梯度计算
        for data, target in loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            pred = output.argmax(dim=1)
            total_correct += (pred == target).sum().item()
            total_samples += target.size(0)

    # D9: 按样本数加权平均准确率
    final_accuracy = total_correct / total_samples if total_samples > 0 else 0.0
    print(f"Accuracy: {final_accuracy:.4f}  (correct={total_correct}/{total_samples})")
    return final_accuracy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniImageNet Evaluation")
    parser.add_argument("--checkpoint", type=str, required=True, help="模型 checkpoint 路径")
    parser.add_argument("--data-dir", type=str, default="./data/", help="数据目录路径")
    parser.add_argument("--batch-size", type=int, default=32, help="批次大小")
    parser.add_argument("--device", type=str, default=None, help="设备（默认自动检测）")
    args = parser.parse_args()

    if args.device is None:
        if torch.cuda.is_available():
            args.device = "cuda:0"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            args.device = "mps"
        else:
            args.device = "cpu"

    evaluate(args.checkpoint, args.data_dir, args.batch_size, args.device)
