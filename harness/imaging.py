"""Image loading, 8-bit rendering and sizing to the model's visual-token budget (SPEC §6.1, §11.2)."""
from __future__ import annotations

import base64
import io
import math
from pathlib import Path

import numpy as np
from PIL import Image

PATCH = 28
MAX_B64_BYTES = int(9.5 * 1024 * 1024)
DICOM_SUFFIXES = {".dcm", ".dicom"}

RENDER_RECIPE = (
    "8-bit grayscale. DICOM: modality LUT -> VOI LUT -> invert if MONOCHROME1 -> min-max to 0..255. "
    "16-bit/float PNG: min-max to 0..255. 8-bit inputs unchanged. "
    "Resize (never upscale) with LANCZOS to fit max_long_edge and ceil(w/28)*ceil(h/28) <= max_visual_tokens. "
    "Saved as PNG without metadata."
)


def visual_tokens(w: int, h: int, patch: int = PATCH) -> int:
    return math.ceil(w / patch) * math.ceil(h / patch)


def fit_size(w: int, h: int, max_edge: int, max_tokens: int, patch: int = PATCH) -> tuple[int, int]:
    """Largest size <= original whose long edge <= max_edge and visual tokens <= max_tokens."""
    if w <= 0 or h <= 0:
        raise ValueError(f"invalid image size {w}x{h}")
    if max(w, h) <= max_edge and visual_tokens(w, h, patch) <= max_tokens:
        return w, h
    scale = min(1.0, max_edge / max(w, h), math.sqrt(max_tokens * patch * patch / (w * h)))
    while True:
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        if max(nw, nh) <= max_edge and visual_tokens(nw, nh, patch) <= max_tokens:
            return nw, nh
        scale *= 0.995


def _to_uint8(arr) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float64)
    finite = np.isfinite(arr)
    if not finite.any():
        return np.zeros(arr.shape, dtype=np.uint8)
    lo, hi = float(arr[finite].min()), float(arr[finite].max())
    if hi <= lo:
        return np.zeros(arr.shape, dtype=np.uint8)
    out = (arr - lo) / (hi - lo) * 255.0
    out = np.nan_to_num(out, nan=0.0, posinf=255.0, neginf=0.0)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def is_dicom(path: str | Path) -> bool:
    path = Path(path)
    if path.suffix.lower() in DICOM_SUFFIXES:
        return True
    try:
        with open(path, "rb") as f:
            head = f.read(132)
        return len(head) == 132 and head[128:132] == b"DICM"
    except OSError:
        return False


def _load_dicom(path: Path) -> Image.Image:
    try:
        import pydicom
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError("pydicom is required to read DICOM files: pip install pydicom") from exc
    try:
        from pydicom.pixels import apply_modality_lut, apply_voi_lut  # pydicom >= 3
    except ImportError:  # pragma: no cover
        from pydicom.pixel_data_handlers.util import apply_modality_lut, apply_voi_lut  # pydicom 2.x

    ds = pydicom.dcmread(str(path))
    arr = ds.pixel_array
    if arr.ndim == 3:
        if int(getattr(ds, "SamplesPerPixel", 1)) == 3:
            arr = arr.astype(np.float64).mean(axis=-1)
        else:
            arr = arr[0]  # first frame of a multi-frame object
    arr = apply_modality_lut(arr, ds)
    arr = apply_voi_lut(arr, ds)
    arr = np.asarray(arr, dtype=np.float64)
    if str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1":
        arr = arr.max() - arr
    return Image.fromarray(_to_uint8(arr))


def load_grayscale(path: str | Path) -> Image.Image:
    """Return an 8-bit grayscale (mode 'L') image from PNG/JPG/DICOM."""
    path = Path(path)
    if is_dicom(path):
        return _load_dicom(path)
    with Image.open(path) as im:
        im.load()
        if im.mode in ("I;16", "I;16B", "I;16L", "I;16N", "I", "F"):
            return Image.fromarray(_to_uint8(np.asarray(im)))
        if im.mode == "L":
            return im.copy()
        return im.convert("L")


def prepare_image(src: str | Path, dst: str | Path, max_edge: int, max_tokens: int) -> dict:
    """Render src to an 8-bit PNG at dst within the size budget. Returns size info."""
    img = load_grayscale(src)
    w, h = img.size
    nw, nh = fit_size(w, h, max_edge, max_tokens)
    if (nw, nh) != (w, h):
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")  # no pnginfo passed, so no text metadata is written
    data = buf.getvalue()
    b64_len = len(base64.b64encode(data))
    if b64_len > MAX_B64_BYTES:
        raise RuntimeError(f"{src}: rendered PNG is {b64_len} bytes in base64, over the 9.5 MB limit")
    Path(dst).write_bytes(data)
    return {"orig_size": [w, h], "size": [nw, nh], "visual_tokens": visual_tokens(nw, nh)}
