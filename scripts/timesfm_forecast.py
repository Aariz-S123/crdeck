"""TimesFM 2.5 inference on CPU. Runs in its own environment, .venv-timesfm (requirements-timesfm.txt), so the
project's pinned packages never need torch. crdeck.futuremeta.timesfm_runner writes the input and reads the output.

    .venv-timesfm/Scripts/python scripts/timesfm_forecast.py <input.npz> <output.npz> <repo> <context> <horizon> <batch>

Input holds context_<i> (series x time, NaN for gaps) and horizon_<i>. Output holds point_<i> (series x horizon),
quantile_<i> (series x horizon x 10: the mean, then the 10% to 90% deciles), and model_file.
"""

from __future__ import annotations

import sys

import numpy as np
import timesfm
import torch
from huggingface_hub import hf_hub_download


def main(src: str, dst: str, repo: str, context: str, horizon: str, batch: str) -> None:
    torch.manual_seed(0)
    weights = hf_hub_download(repo_id=repo, filename="model.safetensors")
    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(repo)
    model.compile(timesfm.ForecastConfig(
        max_context=int(context), max_horizon=int(horizon), per_core_batch_size=int(batch), normalize_inputs=True,
        use_continuous_quantile_head=True, force_flip_invariance=True, infer_is_positive=True, fix_quantile_crossing=True))
    out: dict[str, np.ndarray] = {"model_file": np.array(weights.replace("\\", "/"))}
    with np.load(src, allow_pickle=False) as data:
        groups = sorted(int(k.split("_")[1]) for k in data.files if k.startswith("context_"))
        for done, i in enumerate(groups, 1):
            contexts = data[f"context_{i}"]
            point, quantile = model.forecast(horizon=int(data[f"horizon_{i}"]), inputs=[row.astype(np.float64) for row in contexts])
            out[f"point_{i}"], out[f"quantile_{i}"] = np.asarray(point), np.asarray(quantile)
            print(f"group {done}/{len(groups)}: {contexts.shape[0]} series, {contexts.shape[1]} points", flush=True)
    np.savez_compressed(dst, **out)


if __name__ == "__main__":
    main(*sys.argv[1:7])
