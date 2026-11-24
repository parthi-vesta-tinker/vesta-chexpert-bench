"""Test double for the Anthropic Messages and Message Batches APIs (SPEC §11.2). Never used for real results.

It reads the synthetic stripe encoding from the first frontal image of each request (SPEC §12), so a high
AUROC in the self-test proves that each case's own images reached its own request. It never sees the
reference standard.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
from types import SimpleNamespace

import numpy as np
from PIL import Image

from .common import PRIMARY

NEG_LEVEL, POS_LEVEL = 70.0, 170.0


def _first_frontal_image(content: list) -> str:
    for i, block in enumerate(content):
        if block.get("type") == "text" and "(frontal)" in block.get("text", "") and i + 1 < len(content):
            nxt = content[i + 1]
            if nxt.get("type") == "image":
                return nxt["source"]["data"]
    for block in content:
        if block.get("type") == "image":
            return block["source"]["data"]
    raise ValueError("request contains no image")


class MockClient:
    def __init__(self, seed: int = 0, noise: float = 10.0, fail_rate: float = 0.0):
        self.seed, self.noise, self.fail_rate = seed, noise, fail_rate
        self._lock = threading.Lock()
        self._calls: dict[str, int] = {}
        self.total_calls = 0
        self.messages = _Messages(self)

    def respond(self, params: dict):
        content = params["messages"][0]["content"]
        b64 = _first_frontal_image(content)
        raw = base64.b64decode(b64)
        key = hashlib.sha256(raw).hexdigest()
        with self._lock:
            n = self._calls.get(key, 0)
            self._calls[key] = n + 1
            self.total_calls += 1
        rng = np.random.default_rng(int.from_bytes(hashlib.sha256(f"{self.seed}|{key}|{n}".encode()).digest()[:8], "big"))

        if rng.random() < self.fail_rate:
            text = "I can't give a structured answer for this study."
        else:
            img = np.asarray(Image.open(io.BytesIO(raw)).convert("L"), dtype=np.float64)
            bands = np.array_split(np.arange(img.shape[0]), len(PRIMARY))
            probs = {}
            for finding, rows in zip(PRIMARY, bands):
                level = img[rows].mean()
                p = (level - NEG_LEVEL) / (POS_LEVEL - NEG_LEVEL) * 100 + rng.normal(0, self.noise)
                probs[finding] = int(np.clip(round(p), 0, 100))
            nf = 100 - max(probs[f] for f in PRIMARY) + rng.normal(0, self.noise)
            probs["No Finding"] = int(np.clip(round(nf), 0, 100))
            text = json.dumps(probs)

        n_images = sum(1 for b in content if b.get("type") == "image")
        usage = SimpleNamespace(input_tokens=300 + 4784 * n_images, output_tokens=60)
        return SimpleNamespace(
            id=f"mock_{key[:12]}_{n}",
            model="mock",
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=text)],
            usage=usage,
        )


class _Messages:
    def __init__(self, client: MockClient):
        self._client = client
        self.batches = _Batches(client)

    def create(self, **params):
        return self._client.respond(params)


class _Batches:
    """Processes each batch immediately; retrieve() always reports 'ended'."""

    def __init__(self, client: MockClient):
        self._client = client
        self._store: dict[str, list] = {}
        self._n = 0

    def create(self, requests: list):
        self._n += 1
        batch_id = f"mock_batch_{self._n}"
        results = []
        for req in requests:
            msg = self._client.respond(req["params"])
            results.append(SimpleNamespace(custom_id=req["custom_id"],
                                           result=SimpleNamespace(type="succeeded", message=msg)))
        self._store[batch_id] = results
        return SimpleNamespace(id=batch_id, processing_status="in_progress")

    def retrieve(self, batch_id: str):
        return SimpleNamespace(id=batch_id, processing_status="ended")

    def results(self, batch_id: str):
        return iter(self._store[batch_id])
