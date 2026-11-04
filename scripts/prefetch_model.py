"""Prefetch the default model into the HF cache, retaining large downloads on failure."""
import hashlib
import os
from pathlib import Path
import time

import httpx
from filelock import FileLock

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def resumable_download(url, destination, expected_sha256, expected_size, client=None, attempts=5):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".resume")
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=httpx.Timeout(60, connect=20))
    try:
        for attempt in range(attempts):
            offset = partial.stat().st_size if partial.exists() else 0
            if offset == expected_size:
                break
            if offset > expected_size:
                raise ValueError("Partial file exceeds expected model size; refusing to overwrite it.")
            try:
                headers = {"Range": f"bytes={offset}-"} if offset else {}
                with client.stream("GET", url, headers=headers) as response:
                    response.raise_for_status()
                    if offset and (response.status_code != 206 or not response.headers.get(
                            "content-range", "").startswith(f"bytes {offset}-")):
                        raise ValueError("Server did not honor Range; partial download was preserved.")
                    with partial.open("ab") as output:
                        downloaded = offset
                        next_report = downloaded + 50 * 1024 * 1024
                        for block in response.iter_bytes(chunk_size=64 * 1024):
                            downloaded += len(block)
                            if downloaded > expected_size:
                                raise ValueError("Download exceeds expected model size.")
                            output.write(block)
                            if downloaded >= next_report:
                                print(f"Model weights: {downloaded / 1048576:.1f}/{expected_size / 1048576:.1f} MiB", flush=True)
                                next_report += 50 * 1024 * 1024
                if partial.stat().st_size != expected_size:
                    raise httpx.ReadError("Incomplete model response")
                break
            except httpx.HTTPError:
                if attempt + 1 == attempts:
                    raise
                print("Download interrupted; resuming retained bytes.", flush=True)
                time.sleep(min(attempt + 1, 5))
        digest = hashlib.sha256()
        with partial.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("Model checksum mismatch; refusing to use these weights.")
        os.replace(partial, destination)
    finally:
        if owns_client:
            client.close()


def main():
    from dotenv import load_dotenv
    load_dotenv()
    from huggingface_hub import get_hf_file_metadata, hf_hub_url, snapshot_download
    home = Path(os.getenv("HF_HOME", "./data/model-cache")).resolve()
    home.mkdir(parents=True, exist_ok=True)
    cache = home / "hub"
    metadata = get_hf_file_metadata(hf_hub_url(MODEL, "model.safetensors"))
    digest = metadata.etag.strip('"')
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Expected a SHA-256 content identifier from HF.")
    repo = cache / ("models--" + MODEL.replace("/", "--"))
    weights = repo / "blobs" / digest
    with FileLock(str(home / "prefetch.lock")):
        if not weights.exists():
            resumable_download(hf_hub_url(MODEL, "model.safetensors", revision=metadata.commit_hash),
                               weights, digest, metadata.size)
        snapshot = repo / "snapshots" / metadata.commit_hash
        snapshot.mkdir(parents=True, exist_ok=True)
        link = snapshot / "model.safetensors"
        if not link.exists():
            link.symlink_to(Path("../../blobs") / digest)
        (repo / "refs").mkdir(exist_ok=True)
        (repo / "refs" / "main").write_text(metadata.commit_hash)
    # Config/tokenizer files are small relative to the checkpoint. Never redownload weights here.
    snapshot_download(MODEL, revision=metadata.commit_hash, cache_dir=str(cache),
                      allow_patterns=["*.json", "*.txt", "*.model"],
                      ignore_patterns=["onnx/*", "openvino/*"], max_workers=2)
    print(f"Model cache ready: {home}", flush=True)


if __name__ == "__main__":
    main()
