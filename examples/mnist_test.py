#!/usr/bin/env python
"""
MNIST setup-verification / probe job for GT PACE Phoenix.

Two jobs in one:

1. VERIFICATION - proves your setup works end to end: conda env, GPU visibility,
   scratch I/O, sbatch submission, and log retrieval.

2. PROBE - reports peak host RAM and peak GPU VRAM actually used, so you can size
   a real job from measurement instead of guessing. Pair it with:
       sacct -j <job_id> --format=JobID,MaxRSS,Elapsed
   and request roughly the measured peak x 1.3-1.5 for the real run.

Modes:
  --download-only : fetch MNIST into --data-dir and exit (run on the LOGIN node)
  --smoke         : a handful of batches only, to prove the pipeline works
  (default)       : full run of --epochs epochs

Expected result of a full run: ~99% validation accuracy in well under a minute
on a single V100.
"""

import argparse
import json
import os
import time

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms


class SmallCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, 3, 1)
        self.conv2 = nn.Conv2d(32, 64, 3, 1)
        self.drop = nn.Dropout(0.25)
        self.fc1 = nn.Linear(9216, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2)
        x = self.drop(x)
        x = torch.flatten(x, 1)
        x = F.relu(self.fc1(x))
        return self.fc2(x)


def build_loaders(data_dir, batch_size, workers, download):
    tf = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.1307,), (0.3081,)),
    ])
    train = datasets.MNIST(data_dir, train=True, download=download, transform=tf)
    test = datasets.MNIST(data_dir, train=False, download=download, transform=tf)
    kw = dict(num_workers=workers, pin_memory=torch.cuda.is_available(),
              persistent_workers=workers > 0)
    return (DataLoader(train, batch_size=batch_size, shuffle=True, **kw),
            DataLoader(test, batch_size=1000, shuffle=False, **kw))


def evaluate(model, loader, device, max_batches=None):
    model.eval()
    loss_sum, correct, seen = 0.0, 0, 0
    with torch.no_grad():
        for i, (x, y) in enumerate(loader):
            if max_batches is not None and i >= max_batches:
                break
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            out = model(x)
            loss_sum += F.cross_entropy(out, y, reduction="sum").item()
            correct += out.argmax(1).eq(y).sum().item()
            seen += y.numel()
    return loss_sum / max(seen, 1), 100.0 * correct / max(seen, 1)


def peak_host_ram_gb():
    """Peak resident set size of this process, in GB. Linux only; None elsewhere."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / (1024.0 ** 2)
    except OSError:
        pass
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="./data")
    p.add_argument("--out-dir", default="./results")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch-size", type=int, default=128)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--smoke", action="store_true",
                   help="run only --smoke-batches batches of 1 epoch")
    p.add_argument("--smoke-batches", type=int, default=20)
    p.add_argument("--download-only", action="store_true")
    p.add_argument("--download", action="store_true",
                   help="allow torchvision to download MNIST if missing")
    args = p.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)

    # Staging step: run this on the LOGIN node so the GPU job never depends on
    # outbound network access.
    if args.download_only:
        datasets.MNIST(args.data_dir, train=True, download=True)
        datasets.MNIST(args.data_dir, train=False, download=True)
        print(f"MNIST ready in {os.path.abspath(args.data_dir)}")
        return

    os.makedirs(args.out_dir, exist_ok=True)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"host        : {os.uname().nodename}")
    print(f"torch       : {torch.__version__}")
    print(f"device      : {device}")
    if device.type == "cuda":
        print(f"gpu         : {torch.cuda.get_device_name(0)}")
        print(f"gpu mem GB  : {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f}")
        torch.cuda.reset_peak_memory_stats()
    else:
        # Expected on a login node - they have no GPU. Inside a job with
        # --gres=gpu:N this means something is wrong.
        print("WARNING: no CUDA device visible; running on CPU")

    train_loader, test_loader = build_loaders(
        args.data_dir, args.batch_size, args.workers, args.download)
    print(f"train/test  : {len(train_loader.dataset)}/{len(test_loader.dataset)} images")

    model = SmallCNN().to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    epochs = 1 if args.smoke else args.epochs
    max_batches = args.smoke_batches if args.smoke else None
    history = []
    t_start = time.time()

    for epoch in range(1, epochs + 1):
        model.train()
        t0 = time.time()
        for i, (x, y) in enumerate(train_loader):
            if max_batches is not None and i >= max_batches:
                break
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            opt.zero_grad(set_to_none=True)
            loss = F.cross_entropy(model(x), y)
            loss.backward()
            opt.step()
            if i % 100 == 0:
                print(f"  epoch {epoch} batch {i:4d}  loss {loss.item():.4f}", flush=True)
        val_loss, val_acc = evaluate(model, test_loader, device,
                                     max_batches=2 if args.smoke else None)
        dt = time.time() - t0
        print(f"epoch {epoch}: val_loss {val_loss:.4f}  val_acc {val_acc:.2f}%  ({dt:.1f}s)",
              flush=True)
        history.append({"epoch": epoch, "val_loss": val_loss,
                        "val_acc": val_acc, "seconds": dt})

    # ---- Probe output: measure, do not guess, when sizing the real job. ----
    peak_vram = (torch.cuda.max_memory_allocated() / 1e9) if device.type == "cuda" else None
    peak_vram_reserved = (torch.cuda.max_memory_reserved() / 1e9) if device.type == "cuda" else None
    peak_ram = peak_host_ram_gb()

    summary = {
        "mode": "smoke" if args.smoke else "full",
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
        "epochs_run": epochs,
        "total_seconds": time.time() - t_start,
        "peak_vram_allocated_gb": peak_vram,
        "peak_vram_reserved_gb": peak_vram_reserved,
        "peak_host_ram_gb": peak_ram,
        "history": history,
        "final_val_acc": history[-1]["val_acc"],
    }
    tag = "smoke" if args.smoke else "full"
    out = os.path.join(args.out_dir,
                       f"summary_{tag}_{os.environ.get('SLURM_JOB_ID', 'local')}.json")
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nTOTAL {summary['total_seconds']:.1f}s  final_val_acc {summary['final_val_acc']:.2f}%")
    if peak_vram is not None:
        print(f"peak VRAM   : {peak_vram:.2f} GB allocated / {peak_vram_reserved:.2f} GB reserved")
    if peak_ram is not None:
        print(f"peak host RAM: {peak_ram:.2f} GB")
    print("^ size the real job from these numbers (x1.3-1.5 headroom), not from guesswork")
    print(f"summary written to {out}")


if __name__ == "__main__":
    main()
