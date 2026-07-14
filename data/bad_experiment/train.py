"""图像分类训练脚本 —— MiniImageNet Few-Shot Baseline.

缺陷清单（共 8 个已知缺陷，供审计评估对照）：
  D1: 未设置任何随机种子（random / numpy / torch / cudnn 全未固定）
  D2: 数据路径硬编码为 /home/user/data/MiniImageNet/
  D3: 设备硬编码为 cuda:0
  D4: batch_size 写死在代码中，不可通过命令行配置
  D5: train_test_split 未传入 random_state，每次运行划分不同
  D6: scikit-learn 的 import 未在 requirements.txt 中声明
  D7: checkpoint 保存路径硬编码为 /mnt/gpu_server/checkpoints/
  D8: argparse 定义了参数但不使用，实际值来自全局硬编码变量
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


# ── 超参数（全部硬编码） ──
BATCH_SIZE = 32
LEARNING_RATE = 0.001
EPOCHS = 100
DEVICE = "cuda:0"                           # D3: 硬编码设备
DATA_DIR = "/home/user/data/MiniImageNet/"   # D2: 硬编码数据路径
CHECKPOINT_DIR = "/mnt/gpu_server/checkpoints/"  # D7: 硬编码 checkpoint 路径


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


def train():
    # D1: 未设置任何随机种子
    # 缺失：random.seed(...) / np.random.seed(...) / torch.manual_seed(...)
    #       torch.cuda.manual_seed_all(...) / torch.backends.cudnn.deterministic = True

    # D5: train_test_split 未传入 random_state，每次运行划分不同
    all_files = os.listdir(DATA_DIR + "train/")
    train_files, val_files = train_test_split(all_files, test_size=0.2)

    dataset = MiniImageNetDataset(DATA_DIR)
    loader = DataLoader(
        dataset,
        batch_size=BATCH_SIZE,   # D4: 不可通过命令行配置
        shuffle=True,
        num_workers=4,
    )

    model = ConvNet().to(DEVICE)  # D3
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.CrossEntropyLoss()

    for epoch in range(EPOCHS):
        model.train()
        for batch_idx, (data, target) in enumerate(loader):
            data, target = data.to(DEVICE), target.to(DEVICE)
            optimizer.zero_grad()
            output = model(data)
            loss = criterion(output, target)
            loss.backward()
            optimizer.step()

        # D7: checkpoint 保存到硬编码路径
        os.makedirs(CHECKPOINT_DIR, exist_ok=True)
        torch.save(
            {"epoch": epoch, "model_state_dict": model.state_dict()},
            CHECKPOINT_DIR + f"model_epoch{epoch}.pt",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # D8: 定义了参数但实际训练代码用的是全局硬编码变量
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--lr", type=float, default=LEARNING_RATE)
    args = parser.parse_args()
    train()
