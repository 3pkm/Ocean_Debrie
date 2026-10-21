"""
Export trained PyTorch DebrisUNet to ONNX and verify numerical parity.
Follows plan.md Section 7 & execution_plan.md Phase 1 Task 1.5.
Checks:
- Dynamic spatial or 256x256 dimensions
- Input tensor name: 'input', Output tensor name: 'output'
- Max absolute difference between PyTorch and ONNX Runtime is < 1e-4
"""

import argparse
import logging
import os
import shutil
import sys
import tempfile
from typing import Optional

# Ensure workspace root is in sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import onnx
import onnxruntime as ort
import torch

from core.infer import get_default_model_cache_path
from model.unet import DebrisUNet

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("export_onnx")


def export_model_to_onnx(
    model: DebrisUNet,
    output_path: str,
    tile_size: int = 256,
    device: str = "cpu",
    tolerance: float = 1e-4,
) -> str:
    """
    Exports a trained PyTorch DebrisUNet model to ONNX, verifies the model graph,
    and tests numerical parity against ONNX Runtime.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    model = model.to(device)
    model.eval()

    # Dummy input with shape (1, 14, tile_size, tile_size)
    dummy_input = torch.randn(1, 14, tile_size, tile_size, device=device)

    logger.info(f"Exporting PyTorch model to ONNX at {output_path}...")
    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        export_params=True,
        opset_version=14,
        do_constant_folding=True,
        dynamo=False,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={
            "input": {0: "batch_size", 2: "height", 3: "width"},
            "output": {0: "batch_size", 2: "height", 3: "width"},
        },
    )

    # 1. Check graph integrity with onnx.checker
    onnx_model = onnx.load(output_path)
    onnx.checker.check_model(onnx_model)
    logger.info("ONNX graph verification passed.")

    # 2. Verify parity against ONNX Runtime
    with torch.no_grad():
        py_output = model(dummy_input, return_prob=True).cpu().numpy()

    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(output_path, sess_options, providers=["CPUExecutionProvider"])

    ort_input = {session.get_inputs()[0].name: dummy_input.cpu().numpy()}
    ort_output = session.run([session.get_outputs()[0].name], ort_input)[0]

    max_diff = float(np.max(np.abs(py_output - ort_output)))
    mean_diff = float(np.mean(np.abs(py_output - ort_output)))
    logger.info(f"Parity Test Results: Max Abs Diff = {max_diff:.6e}, Mean Abs Diff = {mean_diff:.6e}")

    if max_diff >= tolerance:
        raise ValueError(
            f"Parity check failed: max difference {max_diff:.6e} exceeded tolerance {tolerance:.6e}"
        )

    logger.info(f"Success! Model exported and verified with max diff < {tolerance:.1e}")

    # Optionally copy to local default cache path so dev_server & tests immediately use it
    default_cache = get_default_model_cache_path()
    try:
        shutil.copyfile(output_path, default_cache)
        logger.info(f"Synchronized verified model to default cache: {default_cache}")
    except Exception as e:
        logger.warning(f"Could not copy to default cache ({default_cache}): {e}")

    return output_path


def main():
    parser = argparse.ArgumentParser(description="Export PyTorch DebrisUNet to ONNX")
    parser.add_argument("--checkpoint", type=str, default=None, help="Path to .pth checkpoint file")
    parser.add_argument(
        "--output",
        type=str,
        default="model/weights/debris_unet.onnx",
        help="Target output .onnx path",
    )
    parser.add_argument("--base-features", type=int, default=32, help="Base feature channels in UNet")
    args = parser.parse_args()

    model = DebrisUNet(in_channels=14, out_channels=1, base_features=args.base_features)

    if args.checkpoint and os.path.exists(args.checkpoint):
        logger.info(f"Loading checkpoint weights from {args.checkpoint}...")
        state_dict = torch.load(args.checkpoint, map_location="cpu")
        model.load_state_dict(state_dict)
    else:
        logger.info("No checkpoint provided; exporting initialized architecture.")

    export_model_to_onnx(model, args.output)


if __name__ == "__main__":
    main()
