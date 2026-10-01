"""Thumbnail generation via model-router proxy endpoint."""

from __future__ import annotations

import base64
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def _get_env_val(key: str) -> str:
    """Read a specific key from the root .env file without external dependencies."""
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def generate_thumbnail(prompt: str, out_path: str, size: str = "1280x720") -> str:
    """Generate a thumbnail image using model-router gpt-image-2 endpoint and write to out_path."""
    url = _get_env_val("MODEL_ROUTER_URL").rstrip("/")
    if not url:
        url = "http://127.0.0.1:8317"
    key = _get_env_val("MODEL_ROUTER_KEY")

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    endpoint = f"{url}/v1/images/generations"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": "gpt-image-2", "prompt": prompt, "size": size}

    try:
        resp = requests.post(endpoint, json=body, headers=headers, timeout=90)
        resp.raise_for_status()
        data = resp.json()
        b64_str = data["data"][0]["b64_json"]
        img_bytes = base64.b64decode(b64_str)
        out_p.write_bytes(img_bytes)
        return str(out_p)
    except Exception as e:
        raise RuntimeError(
            f"Thumbnail generation failed for prompt '{prompt[:50]}...': {e}"
        ) from e


def generate_variants(
    base_prompt: str, out_dir: str, variants: list[str]
) -> list[str]:
    """Generate thumbnail variants by appending suffixes to base_prompt and return generated file paths."""
    out_d = Path(out_dir)
    out_d.mkdir(parents=True, exist_ok=True)
    generated_paths: list[str] = []

    for idx, suffix in enumerate(variants, start=1):
        prompt = f"{base_prompt}, {suffix}" if suffix else base_prompt
        thumb_path = out_d / f"thumb_{idx}.png"
        try:
            res_path = generate_thumbnail(prompt, str(thumb_path))
            generated_paths.append(res_path)
        except Exception as e:
            print(f"  thumbnails: variant {idx} failed: {e}")
            continue

    return generated_paths
