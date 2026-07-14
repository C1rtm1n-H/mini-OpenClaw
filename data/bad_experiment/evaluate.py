"""评估脚本 —— 缺陷清单：
  D9: accuracy 按 batch 简单平均（未按 batch 大小加权），小 batch 被过度代表
  D10: 使用 sklearn.metrics.accuracy_score 但未在 requirements.txt 声明
  D11: model.eval() 和 torch.no_grad() 缺失，评估时仍处于训练模式
"""

import torch
from sklearn.metrics import accuracy_score
from train import ConvNet, MiniImageNetDataset, DEVICE, BATCH_SIZE, DATA_DIR
from torch.utils.data import DataLoader


def evaluate(checkpoint_path: str):
    model = ConvNet()
    checkpoint = torch.load(checkpoint_path, map_location=DEVICE)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.to(DEVICE)

    dataset = MiniImageNetDataset(DATA_DIR, split="test")
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=False)

    # D11: 缺少 model.eval() 和 torch.no_grad()
    batch_accuracies = []
    for data, target in loader:
        data, target = data.to(DEVICE), target.to(DEVICE)
        output = model(data)
        pred = output.argmax(dim=1)
        acc = accuracy_score(target.cpu(), pred.cpu())
        batch_accuracies.append(acc)

    # D9: 直接对 batch 准确率取平均，未按 batch 大小加权
    final_accuracy = sum(batch_accuracies) / len(batch_accuracies)
    print(f"Accuracy: {final_accuracy:.4f}")
    return final_accuracy


if __name__ == "__main__":
    evaluate("/mnt/gpu_server/checkpoints/model_epoch99.pt")
