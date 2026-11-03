"""Copy the website to a folder for a host with a per-file size limit, splitting model files that are too big.

    python scripts/split_web_models.py <out_dir>                  # 15,000,000-byte pieces (Artifact limit is 16 MB)
    python scripts/split_web_models.py <out_dir> --max-bytes N

Writes only the split model files into <out_dir>/models/:
  <slug>.parts.json         {"parts": ["<slug>.part1.txt", ...], "bytes": <size of the original>}
  <slug>.part<k>.txt        consecutive pieces of the original file's text; joined in order they are the file
The whole file is not copied there. web/common.js (getModelJSON) loads <slug>.json when it exists and falls
back to the parts only when it is missing, so a full local copy of the site is unaffected.
Every other file is published as it is; this script doesn't touch web/.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def split(src: Path, out: Path, max_bytes: int) -> list[str]:
    text = src.read_text(encoding="utf-8")
    if not text.isascii():
        raise SystemExit(f"{src.name} is not ASCII; piece sizes would no longer be byte sizes")
    names = []
    for k, start in enumerate(range(0, len(text), max_bytes), 1):
        name = f"{src.stem}.part{k}.txt"
        (out / name).write_text(text[start:start + max_bytes], encoding="utf-8", newline="")
        names.append(name)
    (out / f"{src.stem}.parts.json").write_text(json.dumps({"parts": names, "bytes": len(text)}), encoding="utf-8")
    joined = "".join((out / n).read_text(encoding="utf-8") for n in names)
    if joined != text:
        raise SystemExit(f"{src.name}: the pieces don't join back into the file")
    return names


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--max-bytes", type=int, default=15_000_000)
    a = ap.parse_args()
    out = a.out_dir / "models"
    out.mkdir(parents=True, exist_ok=True)
    for src in sorted((WEB / "models").glob("*.json")):
        if src.stat().st_size > a.max_bytes:
            names = split(src, out, a.max_bytes)
            print(f"{src.name}: {src.stat().st_size:,} bytes -> {len(names)} parts")


if __name__ == "__main__":
    main()
