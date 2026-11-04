import time

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.config import Settings
from backend.service import DocumentService
from backend.vectors import VectorIndex


class TestIndex(VectorIndex):
    """Real persistent Chroma, deterministic embeddings; no model/network required."""
    __test__ = False

    def prepare_chunks(self, chunks):
        return chunks

    def with_context(self, context, text):
        return f"{context}\n{text}" if context else text

    def embed(self, texts):
        return [[1.0, float('capital' in text.lower()), 0.1] for text in texts]


class Generator:
    def answer(self, question, sources):
        return {"claims": [{"quote":sources[0]['text'], "citation_id":sources[0]['citation_id']}],
                "insufficient_evidence": False}


def pdf_bytes(text="Article 1. Banks must maintain capital.", pages=1):
    with fitz.open() as pdf:
        for _ in range(pages):
            page = pdf.new_page()
            if text:
                page.insert_text((72, 100), text)
        return pdf.tobytes()


def wait_status(client, doc_id, expected="ready", approve=True):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = client.get(f"/documents/{doc_id}")
        assert response.status_code == 200
        document = response.json()
        if document["status"] == expected:
            if expected == 'ready' and approve and document['review_status'] != 'approved':
                return approve_document(client, document)
            return document
        if expected == "ready" and document["status"] == "failed":
            pytest.fail(str(document))
        time.sleep(0.02)
    pytest.fail(f"Document did not reach {expected}: {document}")


def approve_document(client, doc):
    metadata = {'document_code':doc.get('document_code') or 'TEST/' + doc['id'][:8],
                'title':'Synthetic test PDF', 'version':doc['version'],
                'source_url':'https://example.org/test.pdf', 'source_note':'Synthetic fixture only',
                'validity_note':'Unknown legal validity; synthetic test',
                'expected_revision':doc['revision'], 'actor':'test reviewer', 'reason':'Set fixture metadata'}
    response = client.patch(f"/documents/{doc['id']}/metadata",json=metadata)
    assert response.status_code == 200,response.text
    response = client.post(f"/documents/{doc['id']}/review",json={
        'expected_revision':response.json()['revision'],'decision':'approved','actor':'test reviewer','note':'Verified synthetic source'})
    assert response.status_code == 200,response.text
    return response.json()


@pytest.fixture
def stack(tmp_path):
    settings = Settings(data_dir=tmp_path)
    index = TestIndex(tmp_path / "chroma", "test-model")
    service = DocumentService(settings, index=index, generator=Generator())
    with TestClient(create_app(settings, service)) as client:
        yield client, service, settings


def upload(client, content=None, name="law.pdf"):
    return client.post("/documents", files={"file": (name, content if content is not None else pdf_bytes(), "application/pdf")})


def test_upload_retrieve_ask_duplicate_delete(stack):
    client, service, _ = stack
    assert client.get("/health").json() == {"status": "ok"}
    content = pdf_bytes()
    response = upload(client, content)
    assert response.status_code == 202
    doc_id = response.json()["document"]["id"]
    doc = wait_status(client, doc_id)
    assert doc["page_count"] == 1 and doc["chunk_count"] > 0
    duplicate = upload(client, content)
    assert duplicate.status_code == 200 and duplicate.json()["duplicate"]
    assert len(client.get("/documents").json()) == 1
    assert client.get(f"/documents/{doc_id}/file").content.startswith(b"%PDF")
    payload = {"question": "capital", "document_ids": [doc_id], "max_distance": 2}
    source = client.post("/search", json=payload).json()["sources"][0]
    assert source["page"] == 1 and source["filename"] == "law.pdf"
    assert source["document_id"] == doc_id and source["text"]
    answer = client.post("/ask", json=payload)
    assert answer.status_code == 200
    assert answer.json()["citations"][0]["document_id"] == doc_id
    assert answer.json()["request_id"]
    assert not answer.json()["insufficient_evidence"]
    assert client.delete(f"/documents/{doc_id}").status_code == 204
    assert client.get(f"/documents/{doc_id}").status_code == 404
    assert service.index.collection.count() == 0
    assert not (service.files / f"{doc_id}.pdf").exists()
    assert client.post("/ask", json={"question": "capital"}).json()["insufficient_evidence"]


def test_multiple_documents_are_isolated(stack):
    client, service, _ = stack
    ids = []
    for name, text in [("a.pdf", "First document capital."), ("b.pdf", "Second document banking.")]:
        doc_id = upload(client, pdf_bytes(text), name).json()["document"]["id"]
        wait_status(client, doc_id)
        ids.append(doc_id)
    assert service.index.collection.count() == 2
    assert len(set(service.index.collection.get()["ids"])) == 2
    hits = client.post("/search", json={"question": "banking", "document_ids": [ids[1]], "max_distance": 2}).json()["sources"]
    assert hits and {h["document_id"] for h in hits} == {ids[1]}
    client.delete(f"/documents/{ids[0]}")
    assert service.index.collection.count() == 1
    assert client.get(f"/documents/{ids[1]}/file").status_code == 200


def test_invalid_files_and_request_validation(stack):
    client, service, _ = stack
    assert upload(client, b"not pdf").status_code == 422
    assert upload(client, b"").status_code == 422
    assert upload(client, b"text", "bad.txt").status_code == 415
    for payload in [{"question": " "}, {"question": "x", "top_k": 0}, {"question": "x", "max_distance": 3}]:
        assert client.post("/search", json=payload).status_code == 422
    assert client.post("/search", json={"question": "x", "document_ids": ["missing"]}).status_code == 404
    assert client.post("/documents/missing/retry").status_code == 404
    assert not list(service.files.glob("*.upload"))


def test_scan_is_failed_not_searchable_and_can_retry(stack):
    client, service, _ = stack
    doc_id = upload(client, pdf_bytes("")).json()["document"]["id"]
    doc = wait_status(client, doc_id, "failed")
    assert "OCR" in doc["error"]
    assert client.post("/search", json={"question": "x", "document_ids": [doc_id]}).status_code == 409
    assert client.post(f"/documents/{doc_id}/retry").status_code == 202
    wait_status(client, doc_id, "failed")
    assert client.delete(f"/documents/{doc_id}").status_code == 204


def test_partial_index_failure_is_hidden_and_retry_cleans_it(stack, monkeypatch):
    client, service, _ = stack
    original = service.index.add
    def failing(*args):
        original(*args)
        raise RuntimeError("Simulated embedding failure")
    monkeypatch.setattr(service.index, "add", failing)
    doc_id = upload(client).json()["document"]["id"]
    wait_status(client, doc_id, "failed")
    assert client.post("/search", json={"question": "x"}).json()["sources"] == []
    assert service.index.collection.count() == 0
    monkeypatch.setattr(service.index, "add", original)
    assert client.post(f"/documents/{doc_id}/retry").status_code == 202
    wait_status(client, doc_id)
    assert service.index.collection.count() == 1
    assert client.post(f"/documents/{doc_id}/retry").status_code == 409


def test_bad_citations_are_rejected(stack, monkeypatch):
    client, service, _ = stack
    doc_id = upload(client).json()["document"]["id"]
    wait_status(client, doc_id)
    monkeypatch.setattr(service.generator, "answer", lambda *_: {
        "answer": "Invented answer [999]", "citation_ids": ["999"], "insufficient_evidence": False})
    result = client.post("/ask", json={"question": "capital", "max_distance": 2}).json()
    assert result["insufficient_evidence"] and not result["citations"]


def test_auth_size_limit_and_pages(tmp_path):
    settings = Settings(data_dir=tmp_path, api_key="secret", max_upload_bytes=1500, max_pages=1)
    service = DocumentService(settings, index=TestIndex(tmp_path / "chroma", "test"), generator=Generator())
    with TestClient(create_app(settings, service)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/documents").status_code == 401
        assert client.get("/documents", headers={"X-API-Key": "wrong"}).status_code == 401
        client.headers["X-API-Key"] = "secret"
        assert client.get("/documents").status_code == 200
        assert upload(client, b"x" * 1501).status_code == 413
        assert upload(client, pdf_bytes(pages=2)).status_code == 422


def test_persistence_and_interrupted_job_recovery(tmp_path):
    settings = Settings(data_dir=tmp_path)
    def new_service():
        return DocumentService(settings, index=TestIndex(tmp_path / "chroma", "test"), generator=Generator())
    service = new_service()
    with TestClient(create_app(settings, service)) as client:
        doc_id = upload(client).json()["document"]["id"]
        wait_status(client, doc_id)
    # Simulate a crash after processing was marked, with a partial/existing index.
    service.registry.update(doc_id, status="processing")
    recovered = new_service()
    with TestClient(create_app(settings, recovered)) as client:
        wait_status(client, doc_id)
        assert recovered.index.collection.count() == 1
        assert client.post("/search", json={"question": "capital", "max_distance": 2}).json()["sources"]


def test_deletion_recovers_on_restart(tmp_path):
    settings = Settings(data_dir=tmp_path)
    service = DocumentService(settings, index=TestIndex(tmp_path / "chroma", "test"), generator=Generator())
    with TestClient(create_app(settings, service)) as client:
        doc_id = upload(client).json()["document"]["id"]
        wait_status(client, doc_id)
    service.registry.update(doc_id, status="deleting")
    recovered = DocumentService(settings, index=TestIndex(tmp_path / "chroma", "test"), generator=Generator())
    with TestClient(create_app(settings, recovered)) as client:
        deadline = time.monotonic() + 10
        while client.get(f"/documents/{doc_id}").status_code != 404 and time.monotonic() < deadline:
            time.sleep(.02)
        assert client.get(f"/documents/{doc_id}").status_code == 404
        assert recovered.index.collection.count() == 0


def test_missing_llm_key_keeps_search_available(stack):
    from backend.generation import AnswerGenerator
    client, service, _ = stack
    doc_id = upload(client).json()["document"]["id"]
    wait_status(client, doc_id)
    service.generator = AnswerGenerator("", "gpt-4o-mini")
    assert client.post("/search", json={"question": "capital", "max_distance": 2}).json()["sources"]
    assert client.post("/ask", json={"question": "capital", "max_distance": 2}).status_code == 503


def test_single_process_lock_and_model_config_guard(tmp_path):
    from filelock import Timeout
    settings = Settings(data_dir=tmp_path)
    service = DocumentService(settings, index=TestIndex(tmp_path / "chroma", "test"))
    service.start()
    try:
        other = DocumentService(settings)
        with pytest.raises(Timeout):
            other.start()
    finally:
        service.close()
    other_settings = Settings(data_dir=tmp_path, embedding_model="different-model")
    other = DocumentService(other_settings)
    with pytest.raises(RuntimeError, match="configuration changed"):
        other.start()


def test_password_protected_pdf_is_rejected(stack):
    client, _, _ = stack
    with fitz.open(stream=pdf_bytes(), filetype="pdf") as pdf:
        encrypted = pdf.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader")
    response = upload(client, encrypted)
    assert response.status_code == 422 and "mật khẩu" in response.json()["detail"]


@pytest.mark.skipif(not __import__("os").path.exists("/System/Library/Fonts/Supplemental/Arial.ttf"), reason="needs a font with Vietnamese glyphs")
def test_ask_expands_hit_to_clause_siblings_and_heading(stack):
    client, service, _ = stack
    lines = ["Điều 1. Licence conditions", "1. A licence is granted when all of the following hold:",
             "a) Registered enterprise;", "b) Minimum capital of 500 million;", "c) Legal representative not barred.",
             "Điều 2. Other"]
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_font(fontname="vn", fontfile="/System/Library/Fonts/Supplemental/Arial.ttf")
        for i, line in enumerate(lines):
            page.insert_text((72, 100 + 20 * i), line, fontname="vn")
        content = pdf.tobytes()
    doc_id = client.post("/documents", files={"file": ("law.pdf", content, "application/pdf")}).json()["document"]["id"]
    wait_status(client, doc_id)
    seen = {}
    service.generator.answer = lambda question, sources: seen.update(sources=sources) or {"claims": [], "insufficient_evidence": True}
    # Only 'b' matches 'capital' in the fake embedder, but the model must see the whole list.
    client.post("/ask", json={"question": "capital", "top_k": 1, "max_distance": 2})
    texts = [s["text"] for s in seen["sources"]]
    assert texts[0].startswith("Điều 1") and any(t.startswith("a)") for t in texts)
    assert any(t.startswith("b)") for t in texts) and any(t.startswith("c)") for t in texts)
    assert not any(t.startswith("Điều 2") for t in texts)
    assert [s["citation_id"] for s in seen["sources"]] == [str(i) for i in range(1, len(texts) + 1)]


def test_verbatim_check_ignores_line_break_whitespace_but_not_words():
    verbatim = DocumentService._verbatim
    text = "d) Bị rút tiền hàng loạt\nvà có nguy cơ  gây mất an toàn;"
    assert verbatim("Bị rút tiền hàng loạt và có nguy cơ gây mất an toàn;", text) == "Bị rút tiền hàng loạt\nvà có nguy cơ  gây mất an toàn;"
    assert verbatim("Bị rút tiền hàng loạt và không có nguy cơ", text) is None
    assert verbatim("   ", text) is None
    # Model copy slip (lost diacritics) still resolves to the source's own words.
    assert verbatim("Bi rut tien hang loat", text) == "Bị rút tiền hàng loạt"
    assert verbatim("đang chấp hành", "x) dang chấp hành.") == "dang chấp hành"
    assert verbatim("Bị rút tiền hàng loạt và có nguy cơ gây mất an toàn", text) == "Bị rút tiền hàng loạt\nvà có nguy cơ  gây mất an toàn"


@pytest.mark.skipif(not __import__("os").path.exists("/System/Library/Fonts/Supplemental/Arial.ttf"), reason="needs a font with Vietnamese glyphs")
def test_hybrid_search_finds_keyword_match_when_vectors_cannot_tell_chunks_apart(stack):
    client, service, _ = stack
    lines = ["Điều 1. Phạm vi điều chỉnh", "Điều 2. Đối tượng áp dụng", "Điều 3. Giải thích từ ngữ"]
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_font(fontname="vn", fontfile="/System/Library/Fonts/Supplemental/Arial.ttf")
        for i, line in enumerate(lines):
            page.insert_text((72, 100 + 20 * i), line, fontname="vn")
        content = pdf.tobytes()
    doc_id = client.post("/documents", files={"file": ("law.pdf", content, "application/pdf")}).json()["document"]["id"]
    wait_status(client, doc_id)
    # The fake embedder gives all three chunks the same vector, so only BM25 can rank them.
    hits = client.post("/search", json={"question": "đối tượng áp dụng", "top_k": 1, "max_distance": 2}).json()["sources"]
    assert [h["article"] for h in hits] == ["Điều 2"]


def test_continuation_merges_only_overlapping_pieces_of_the_same_clause():
    base = {'document_id': 'd', 'page': 2, 'article': 'Điều 2', 'clause': '5', 'point': ''}
    first = {**base, 'text': 'abc def ghi', 'start_char': 10, 'end_char': 21}
    assert DocumentService._continues(first, {**base, 'text': 'ghi jkl', 'start_char': 18, 'end_char': 25})
    assert not DocumentService._continues(first, {**base, 'text': 'xyz jkl', 'start_char': 18, 'end_char': 25})
    assert not DocumentService._continues(first, {**base, 'text': 'jkl', 'start_char': 21, 'end_char': 24})
    assert not DocumentService._continues(first, {**base, 'text': 'ghi jkl', 'start_char': 18, 'end_char': 25, 'clause': '6'})
    assert not DocumentService._continues(first, {**base, 'text': 'ghi jkl', 'start_char': 18, 'end_char': 25, 'page': 3})



class FakeReranker:
    def __init__(self, scores):
        self._scores = scores

    def scores(self, question, texts):
        return self._scores


def _sources(n):
    return [{'text': f't{i}', 'citation_id': str(i + 1)} for i in range(n)]


def test_rerank_promotes_cross_encoder_favourite_but_keeps_retrieval_signal(stack):
    _, service, _ = stack
    service.reranker = FakeReranker([0.0, 0.1, 9.0, 0.2])
    order = [s['text'] for s in service._rerank('đối tượng', _sources(4))]
    assert order[0] == 't2' and order[1] == 't0'  # cross-encoder winner first, retrieval rank 1 next
    assert sorted(order) == ['t0', 't1', 't2', 't3']


def test_rerank_is_skipped_when_disabled_or_failing(stack):
    _, service, _ = stack
    sources = _sources(3)
    service.reranker = None
    assert service._rerank('q', sources) == sources
    service.reranker = FakeReranker(None)
    assert service._rerank('q', sources) == sources
    service.reranker = FakeReranker([5.0])
    assert service._rerank('q', sources[:1]) == sources[:1]


def test_rerank_skips_unaccented_questions(stack):
    _, service, _ = stack
    service.reranker = FakeReranker([0.0, 0.1, 9.0])
    sources = _sources(3)
    assert service._rerank('doi tuong ap dung', sources) == sources
    assert service._rerank('đối tượng áp dụng', sources) != sources
