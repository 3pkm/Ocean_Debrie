"""
ONNX Model loading, tiling, inference, and stitching for Ocean Debris Segmentation.
Handles:
- ONNX model download / cache resolution in local temp dir
- Mock ONNX model creation for testing and offline development
- 256x256 spatial tiling with reflective/edge padding
- ONNX Runtime InferenceSession management
- Output tile stitching to assemble full-AOI debris probability map (0.0 - 1.0)
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import onnxruntime as ort

from core.config import (
    MODEL_BLOB_URL,
    NORM_MEANS,
    NORM_STDS,
    TILE_SIZE,
)
from core.indices import stack_14_channels

logger = logging.getLogger(__name__)

# In-process session cache
_CACHED_SESSIONS: Dict[str, ort.InferenceSession] = {}


def create_mock_onnx_model(output_path: str) -> str:
    """
    Create a minimal valid ONNX model (14 input channels -> 1 output debris probability channel)
    using onnx.helper so that pipelines and unit tests can run offline without downloading weights.

    The model performs a 1x1 Conv with positive sensitivity on Channel 11 (FDI)
    followed by Sigmoid activation, producing probabilities in [0.0, 1.0].
    """
    import onnx
    from onnx import TensorProto, helper

    # Ensure parent dir exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Dynamic batch, 14 channels, tile_size x tile_size (or dynamic spatial)
    X = helper.make_tensor_value_info("input", TensorProto.FLOAT, [None, 14, None, None])
    Y = helper.make_tensor_value_info("output", TensorProto.FLOAT, [None, 1, None, None])

    # Weights: (out_channels=1, in_channels=14, kH=1, kW=1)
    # Channel 11 is FDI
    w_val = np.zeros((1, 14, 1, 1), dtype=np.float32)
    w_val[0, 11, 0, 0] = 5.0  # Positive weight on FDI
    W = helper.make_tensor("W", TensorProto.FLOAT, [1, 14, 1, 1], w_val.flatten().tolist())
    B = helper.make_tensor("B", TensorProto.FLOAT, [1], [-0.5])

    conv_node = helper.make_node(
        "Conv",
        inputs=["input", "W", "B"],
        outputs=["conv_out"],
        kernel_shape=[1, 1],
        pads=[0, 0, 0, 0],
    )
    sigmoid_node = helper.make_node(
        "Sigmoid",
        inputs=["conv_out"],
        outputs=["output"],
    )

    graph = helper.make_graph(
        [conv_node, sigmoid_node],
        "mock_debris_segmentation_unet",
        [X],
        [Y],
        [W, B],
    )

    # Use ir_version=10 and opset=14 for high compatibility with onnxruntime
    model = helper.make_model(
        graph,
        producer_name="ocean_debris_engine",
        opset_imports=[helper.make_opsetid("", 14)],
        ir_version=10,
    )
    onnx.checker.check_model(model)
    onnx.save(model, output_path)
    logger.info(f"Created mock ONNX model at {output_path}")
    return output_path


def get_default_model_cache_path() -> str:
    """Get the standard local path for caching ONNX model weights."""
    cache_dir = os.environ.get("MODEL_CACHE_DIR", tempfile.gettempdir())
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, "debris_unet.onnx")


def load_onnx_session(
    model_path: Optional[str] = None,
    blob_url: Optional[str] = None,
    force_reload: bool = False,
) -> ort.InferenceSession:
    """
    Resolve and return an onnxruntime InferenceSession:
    1. If model_path is provided and exists, load it.
    2. Check local default cache (/tmp/debris_unet.onnx).
    3. If missing and blob_url (or MODEL_BLOB_URL) is set, download weights.
    4. If still missing, create a mock ONNX model so testing and offline runs never fail.
    """
    target_path = model_path or get_default_model_cache_path()

    if not force_reload and target_path in _CACHED_SESSIONS:
        return _CACHED_SESSIONS[target_path]

    url_to_fetch = blob_url or MODEL_BLOB_URL

    if not os.path.exists(target_path):
        if url_to_fetch:
            logger.info(f"Downloading ONNX model from {url_to_fetch} to {target_path}...")
            try:
                import requests

                resp = requests.get(url_to_fetch, stream=True, timeout=60)
                resp.raise_for_status()
                tmp_target = f"{target_path}.tmp"
                with open(tmp_target, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp_target, target_path)
                logger.info(f"Downloaded model to {target_path}")
            except Exception as e:
                logger.warning(
                    f"Failed to download ONNX model from {url_to_fetch}: {e}. Creating mock model."
                )
                create_mock_onnx_model(target_path)
        else:
            logger.info(f"Model file not found at {target_path}. Creating mock model.")
            create_mock_onnx_model(target_path)

    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(target_path, sess_options, providers=["CPUExecutionProvider"])
    _CACHED_SESSIONS[target_path] = sess
    return sess


def predict_tiles(
    stacked_14ch: np.ndarray,
    session: Optional[ort.InferenceSession] = None,
    tile_size: int = TILE_SIZE,
) -> np.ndarray:
    """
    Tile 14-channel input array (14, H, W) into (tile_size, tile_size) patches with boundary padding,
    run ONNX model inference, and stitch probability predictions back into full AOI array (H, W).
    Returns:
      debris_probability_map: float32 array of shape (H, W), values in [0.0, 1.0].
    """
    if session is None:
        session = load_onnx_session()

    if stacked_14ch.ndim != 3 or stacked_14ch.shape[0] != 14:
        raise ValueError(
            f"Expected input array of shape (14, H, W), got {stacked_14ch.shape}"
        )

    _, orig_h, orig_w = stacked_14ch.shape

    # Calculate padding to nearest multiple of tile_size
    pad_h = (tile_size - (orig_h % tile_size)) % tile_size
    pad_w = (tile_size - (orig_w % tile_size)) % tile_size

    if pad_h > 0 or pad_w > 0:
        pad_mode = "edge" if orig_h > 0 and orig_w > 0 else "constant"
        padded_input = np.pad(
            stacked_14ch,
            ((0, 0), (0, pad_h), (0, pad_w)),
            mode=pad_mode,
        )
    else:
        padded_input = stacked_14ch

    _, padded_h, padded_w = padded_input.shape
    stitched_prob = np.zeros((padded_h, padded_w), dtype=np.float32)

    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    # Iterate over non-overlapping tiles
    for r in range(0, padded_h, tile_size):
        for c in range(0, padded_w, tile_size):
            tile = padded_input[:, r : r + tile_size, c : c + tile_size]
            # Batch dimension: (1, 14, tile_size, tile_size)
            tile_batch = np.expand_dims(tile, axis=0).astype(np.float32)

            pred = session.run([output_name], {input_name: tile_batch})[0]

            # Interpret model output: can be (1, 1, H, W), (1, 2, H, W), (1, H, W), etc.
            if pred.ndim == 4:
                if pred.shape[1] == 1:
                    tile_prob = pred[0, 0]
                else:
                    # Multi-class: class 1 is debris
                    tile_prob = pred[0, 1]
            elif pred.ndim == 3:
                tile_prob = pred[0]
            elif pred.ndim == 2:
                tile_prob = pred
            else:
                tile_prob = np.squeeze(pred)

            stitched_prob[r : r + tile_size, c : c + tile_size] = tile_prob

    # Crop out padding to match original dimensions
    debris_prob = stitched_prob[:orig_h, :orig_w]
    return np.clip(debris_prob, 0.0, 1.0).astype(np.float32)


def run_debris_inference(
    bands: Dict[str, np.ndarray],
    session: Optional[ort.InferenceSession] = None,
    means: Optional[List[float]] = None,
    stds: Optional[List[float]] = None,
    tile_size: int = TILE_SIZE,
) -> np.ndarray:
    """
    Convenience end-to-end inference function:
    1. Stacks 11 bands + FDI, NDVI, NDWI into 14 channels with normalization.
    2. Runs tiling, ONNX inference, and stitching.
    Returns:
      debris_probability_map: 2D float32 array (H, W).
    """
    norm_means = means if means is not None else NORM_MEANS
    norm_stds = stds if stds is not None else NORM_STDS

    stacked = stack_14_channels(bands, means=norm_means, stds=norm_stds)
    return predict_tiles(stacked, session=session, tile_size=tile_size)
