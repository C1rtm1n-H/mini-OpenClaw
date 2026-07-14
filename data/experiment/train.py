"""图像分类训练脚本 —— MiniImageNet Few-Shot Baseline.

修复记录（对应审计报告缺陷）：
  D1: 已修复 —— 设置 random/numpy/torch/cudnn 随机种子
  D2: 已修复 —— 数据路径通过 --data-dir 参数配置，默认相对路径 ./data/
  D3: 已修复 —— 设备自动检测（CUDA/MPS/CPU）
  D4: 已修复 —— batch_size 通过 --batch-size 参数配置
  D5: 已修复 —— train_test_split 传入 random_state=args.seed
  D6: 已修复 —— scikit-learn 已在 requirements.txt 中声明
  D7: 已修复 —— checkpoint 路径通过 --checkpoint-dir 参数配置，默认 ./checkpoints/
  D8: 已修复 —— argparse 参数实际生效，全局硬编码变量已移除
"""

import argparse
import os
import random

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms
from PIL import Image
from sklearn.model_selection import train_test_split


class MiniImageNetDataset(Dataset):
    def __init__(self, root: str, split: str = "train"):
        self.root = root
        self.split = split
        path = os.path.join(root, split)
        self.images = sorted(
            p for p in os.listdir(path) if p.endswith(".jpg")
        )
        self.transform = transforms.Compose([
            transforms.Resize((84, 84)),
            transforms.ToTensor(),
        ])

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        path = os.path.join(self.root, self.split, self.images[idx])
        img = Image.open(path).convert("RGB")
        label = int(self.images[idx].split("_")[0])
        return self.transform(img), label


class ConvNet(nn.Module):
    def __init__(self, num_classes: int = 64):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(3, 64, 3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1),
            nn.BatchNorm2d(128),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(128, 256, 3, padding=1),
            nn.BatchNorm2d(256),
            nn.ReLU(),
            nn.MaxPool2d(2),
        )
        self.fc = nn.Linear(256 * 10 * 10, num_classes)

    def forward(self, x):
        x = self.conv(x)
        x = x.view(x.size(0), -1)
        return self.fc(x)


def set_seed(seed: int):
    """固定所有随机种子，确保可复现。"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def get_device():
    """自动选择可用设备。"""
    if torch.cuda.is_available():
        return "cuda:0"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def train(args):
    # 固定随机种子
    set_seed(args.seed)

    # 自动选择设备
    device = get_device()
    print(f"Using device: {device}")

    # 数据划分（固定 random_state 确保可复现）
    all_files = os.listdir(os.path.join(args.data_dir, "train/"))
    train_files, val_files = train_test_split(
        all_files, test_size=0.2, random_state=args.seed
    )
    print(f"Train samples: {len(train_files)}, Val samples: {len(val_files)}")

    # 数据集与数据加载器
    dataset = MiniImageNetDataset(args.data_dir)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=4,
    )

    # 模型、优化器、损失函数
    model = ConvNet().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.CrossEntropyLoss()

    # 创建 checkpoint 目录
    os.makedirs(args.checkpoint_dir, exist_ok=True)

    for epoch in range(args.epochs):
        model.train()
        running_loss = 0.0
        for batch_idx, (data, target) in enumerate(loader):
            data, target = data.to(device), target.to(device)
            optimizer.zero_grad()
            output = model(data)
            loss = criterion(output, target)
            loss.backward()
            optimizer.step()
            running_loss += loss.item()

        avg_loss = running_loss / len(loader)
        print(f"Epoch {epoch+1}/{args.epochs} - Loss: {avg_loss:.4f}")

        # 保存 checkpoint
        torch.save(
            {"epoch": epoch, "model_state_dict": model.state_dict()},
            os.path.join(args.checkpoint_dir, f"model_epoch{epoch}.pt"),
        )

    # 保存最终模型
    torch.save(
        {"epoch": args.epochs - 1, "model_state_dict": model.state_dict()},
        os.path.join(args.checkpoint_dir, "model_final.pt"),
    )
    print(f"Training complete. Final model saved to {args.checkpoint_dir}/model_final.pt")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MiniImageNet Few-Shot Baseline Training")
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数")
    parser.add_argument("--batch-size", type=int, default=32, help="批次大小")
    parser.add_argument("--lr", type=float, default=0.001, help="学习率")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--data-dir", type=str, default="./data/", help="数据目录路径")
    parser.add_argument("--checkpoint-dir", type=str, default="./checkpoints/", help="模型保存目录")
    args = parser.parse_args()
    train(args)
