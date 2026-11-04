import hashlib
import httpx
from scripts.prefetch_model import resumable_download


class InterruptedStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b"a" * 65536
        raise httpx.ReadTimeout("Connection dropped")


def test_model_download_retains_and_resumes_bytes(tmp_path, monkeypatch):
    body = b"a" * 65536 + b"rest"
    seen = []
    def handler(request):
        seen.append(request.headers.get("range"))
        if len(seen) == 1:
            return httpx.Response(200, stream=InterruptedStream())
        return httpx.Response(206, headers={"Content-Range": f"bytes 65536-{len(body)-1}/{len(body)}"}, content=b"rest")
    monkeypatch.setattr("scripts.prefetch_model.time.sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        path = tmp_path / "weights"
        resumable_download("https://example.test/model", path, hashlib.sha256(body).hexdigest(), len(body), client)
    assert seen == [None, "bytes=65536-"]
    assert path.read_bytes() == body
    assert not path.with_suffix(".resume").exists()


def test_model_download_does_not_use_corrupt_weights(tmp_path):
    import pytest
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"wrong"))) as client:
        path = tmp_path / "weights"
        with pytest.raises(ValueError, match="checksum"):
            resumable_download("https://example.test/model", path, "0" * 64, 5, client)
    assert not path.exists()
    assert path.with_suffix(".resume").read_bytes() == b"wrong"
