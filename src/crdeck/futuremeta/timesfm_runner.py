"""Calls TimesFM in its own environment and caches each forecast by what went in, so reruns skip finished work."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import PROJECT_ROOT


@dataclass(frozen=True)
class Task:
    contexts: np.ndarray   # series x time, NaN for gaps; a series starting later has leading NaNs
    horizon: int


def _digest(task: Task, repo: str, context: int, max_horizon: int) -> str:
    h = hashlib.sha1(f"{repo}|{context}|{max_horizon}|{task.horizon}|{task.contexts.shape}".encode())
    h.update(np.nan_to_num(task.contexts, nan=-1.0).round(10).tobytes())
    return h.hexdigest()


def forecast(tasks: list[Task], settings: dict, cache: Path, python: Path | None = None, verbose: bool = True) -> list[tuple[np.ndarray, np.ndarray]]:
    """(point [series, horizon], quantile [series, horizon, 10]) per task. Runs only the tasks not cached yet."""
    cfg = settings["timesfm"]
    repo, context, max_horizon, batch = cfg["repo"], int(cfg["max_context"]), int(cfg["max_horizon"]), int(cfg["batch_size"])
    cache.mkdir(parents=True, exist_ok=True)
    names = [cache / f"{_digest(t, repo, context, max_horizon)}.npz" for t in tasks]
    todo = sorted({n: t for n, t in zip(names, tasks) if not n.exists()}.items(), key=lambda kv: kv[0].name)
    if todo:
        python = python or PROJECT_ROOT / ".venv-timesfm" / "Scripts" / "python.exe"
        src, dst = cache / "_input.npz", cache / "_output.npz"
        arrays: dict[str, np.ndarray] = {}
        for i, (_, t) in enumerate(todo):
            arrays[f"context_{i}"], arrays[f"horizon_{i}"] = t.contexts.astype(np.float64), np.array(t.horizon)
        np.savez(src, **arrays)
        cmd = [str(python), str(PROJECT_ROOT / "scripts" / "timesfm_forecast.py"), str(src), str(dst), repo, str(context), str(max_horizon), str(batch)]
        if verbose:
            print(f"TimesFM: {len(todo)} forecast group(s), {sum(t.contexts.shape[0] for _, t in todo)} series", flush=True)
        subprocess.run(cmd, check=True)
        with np.load(dst, allow_pickle=False) as out:
            for i, (name, _) in enumerate(todo):
                np.savez_compressed(name, point=out[f"point_{i}"], quantile=out[f"quantile_{i}"])
        src.unlink(); dst.unlink()
    results = []
    for n in names:
        with np.load(n, allow_pickle=False) as d:
            results.append((d["point"], d["quantile"]))
    return results


def model_revision(repo: str) -> str | None:
    """The cached model's commit, from the Hugging Face cache folder (provenance only; None if not found)."""
    root = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{repo.replace('/', '--')}" / "refs" / "main"
    return root.read_text(encoding="utf-8").strip() if root.exists() else None
