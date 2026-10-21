"""
Training pipeline for 14-channel Multispectral Marine Debris Segmentation Engine.
Fulfills Phase 1 Tasks 1.1 - 1.5 from execution_plan.md.
Features:
- Combined Dice Loss + Focal Loss for severe class imbalance
- Metrics: IoU, F1 score, Precision, Recall
- Support for real MARIDA dataset directory or synthetic multi-band benchmark
- Auto-detects NVIDIA CUDA (e.g. RTX 5060) or CPU
- Automated ONNX export & parity check upon completion
"""

import argparse
import logging
import os
import sys
from typing import Tuple

# Ensure workspace root is in sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader

from model.dataset import MaridaDataset
from model.export_onnx import export_model_to_onnx
from model.unet import DebrisUNet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train")


class DiceLoss(nn.Module):
    """Soft Dice Loss for binary segmentation."""

    def __init__(self, eps: float = 1e-6):
        super().__init__()
        self.eps = eps

    def forward(self, pred_probs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        p = pred_probs.view(-1)
        t = targets.view(-1)
        intersection = (p * t).sum()
        dice = (2.0 * intersection + self.eps) / (p.sum() + t.sum() + self.eps)
        return 1.0 - dice


class FocalLoss(nn.Module):
    """Focal Loss for handling rare target classes (marine debris)."""

    def __init__(self, alpha: float = 0.8, gamma: float = 2.0, eps: float = 1e-6):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.eps = eps

    def forward(self, pred_probs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        p = torch.clamp(pred_probs.view(-1), self.eps, 1.0 - self.eps)
        t = targets.view(-1)
        pt = torch.where(t == 1, p, 1 - p)
        alpha_t = torch.where(t == 1, self.alpha, 1 - self.alpha)
        focal_loss = -alpha_t * ((1.0 - pt) ** self.gamma) * torch.log(pt)
        return focal_loss.mean()


class CombinedLoss(nn.Module):
    """Dice + Focal Loss combined."""

    def __init__(self, dice_weight: float = 0.5, focal_weight: float = 0.5):
        super().__init__()
        self.dice = DiceLoss()
        self.focal = FocalLoss()
        self.dice_weight = dice_weight
        self.focal_weight = focal_weight

    def forward(self, pred_probs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        return self.dice_weight * self.dice(pred_probs, targets) + self.focal_weight * self.focal(
            pred_probs, targets
        )


def compute_metrics(pred_probs: torch.Tensor, targets: torch.Tensor, threshold: float = 0.5) -> Tuple[float, float, float, float]:
    """Computes IoU, F1, Precision, and Recall."""
    preds = (pred_probs >= threshold).float().view(-1)
    tgts = targets.view(-1)

    tp = (preds * tgts).sum().item()
    fp = (preds * (1.0 - tgts)).sum().item()
    fn = ((1.0 - preds) * tgts).sum().item()

    precision = tp / (tp + fp + 1e-6)
    recall = tp / (tp + fn + 1e-6)
    f1 = 2 * (precision * recall) / (precision + recall + 1e-6)
    iou = tp / (tp + fp + fn + 1e-6)

    return iou, f1, precision, recall


def train_model(
    data_dir: str = None,
    epochs: int = 10,
    batch_size: int = 8,
    lr: float = 1e-3,
    base_features: int = 32,
    synthetic_samples: int = 100,
    output_dir: str = "model/weights",
):
    os.makedirs(output_dir, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Using compute device: {device} (CUDA Available: {torch.cuda.is_available()})")

    # 1. Datasets & Loaders
    train_dataset = MaridaDataset(
        data_dir=data_dir,
        augment=True,
        synthetic_samples=synthetic_samples,
    )
    val_dataset = MaridaDataset(
        data_dir=data_dir,
        augment=False,
        synthetic_samples=max(20, synthetic_samples // 4),
    )

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    # 2. Architecture & Optimization
    model = DebrisUNet(in_channels=14, out_channels=1, base_features=base_features)
    model.to(device)

    criterion = CombinedLoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_val_iou = -1.0
    best_ckpt_path = os.path.join(output_dir, "best_debris_unet.pth")

    logger.info(f"Starting training for {epochs} epochs on {len(train_dataset)} samples...")

    for epoch in range(1, epochs + 1):
        # Training Phase
        model.train()
        train_loss = 0.0
        for x, y in train_loader:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            probs = model(x, return_prob=True)
            loss = criterion(probs, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        scheduler.step()
        train_loss /= max(1, len(train_loader))

        # Validation Phase
        model.eval()
        val_loss = 0.0
        total_iou, total_f1, total_prec, total_rec = 0.0, 0.0, 0.0, 0.0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(device), y.to(device)
                probs = model(x, return_prob=True)
                val_loss += criterion(probs, y).item()
                iou, f1, prec, rec = compute_metrics(probs, y)
                total_iou += iou
                total_f1 += f1
                total_prec += prec
                total_rec += rec

        val_loss /= max(1, len(val_loader))
        num_val_batches = max(1, len(val_loader))
        mean_iou = total_iou / num_val_batches
        mean_f1 = total_f1 / num_val_batches
        mean_prec = total_prec / num_val_batches
        mean_rec = total_rec / num_val_batches

        logger.info(
            f"Epoch [{epoch:02d}/{epochs:02d}] "
            f"Train Loss: {train_loss:.4f} | "
            f"Val Loss: {val_loss:.4f} | "
            f"Val IoU: {mean_iou:.4f} | "
            f"F1: {mean_f1:.4f} | "
            f"Prec: {mean_prec:.4f} | Rec: {mean_rec:.4f}"
        )

        if mean_iou > best_val_iou:
            best_val_iou = mean_iou
            torch.save(model.state_dict(), best_ckpt_path)
            logger.info(f"-> Saved new best checkpoint with Val IoU {best_val_iou:.4f} to {best_ckpt_path}")

    logger.info("Training complete. Exporting best checkpoint to ONNX...")
    # Load best checkpoint and export
    model.load_state_dict(torch.load(best_ckpt_path, map_location="cpu"))
    onnx_path = os.path.join(output_dir, "debris_unet.onnx")
    export_model_to_onnx(model, onnx_path, device="cpu")
    logger.info(f"Pipeline finished! Verified ONNX model ready at {onnx_path}")


def main():
    parser = argparse.ArgumentParser(description="Train 14-Channel Ocean Debris UNet")
    parser.add_argument("--data-dir", type=str, default=None, help="Directory containing MARIDA patches")
    parser.add_argument("--epochs", type=int, default=10, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=4, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--base-features", type=int, default=32, help="Base feature channels in UNet")
    parser.add_argument("--synthetic-samples", type=int, default=120, help="Synthetic samples if no data dir")
    parser.add_argument("--output-dir", type=str, default="model/weights", help="Directory to save weights")
    args = parser.parse_args()

    train_model(
        data_dir=args.data_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        base_features=args.base_features,
        synthetic_samples=args.synthetic_samples,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
