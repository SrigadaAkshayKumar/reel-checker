"""Optional CLIP embeddings (open_clip + torch, see requirements-ml.txt).

pHash breaks on heavy crops, overlays and colour grading; CLIP is used to
re-score pHash near-misses. Disabled unless USE_CLIP=true and installed."""
from __future__ import annotations

from functools import lru_cache

import numpy as np
from PIL import Image

MODEL = ("ViT-B-32", "laion2b_s34b_b79k")


def available() -> bool:
    try:
        import open_clip  # noqa: F401
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=1)
def _model():
    import open_clip
    model, _, preprocess = open_clip.create_model_and_transforms(MODEL[0], pretrained=MODEL[1])
    model.eval()
    return model, preprocess


def embed(images: list[Image.Image]) -> np.ndarray:
    import torch
    model, preprocess = _model()
    with torch.no_grad():
        batch = torch.stack([preprocess(im) for im in images])
        feats = model.encode_image(batch)
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.cpu().numpy()


def best_cosine(a: np.ndarray, b: np.ndarray) -> float:
    if not len(a) or not len(b):
        return 0.0
    return float((a @ b.T).max())
