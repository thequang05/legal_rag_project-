"""Optional online smoke test using the configured real embedding model, no LLM call.

Run from the repository root: python -m scripts.smoke_embedding
The first run downloads the model. All test documents/index data are temporary.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import time

import pymupdf as fitz
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.config import Settings


def main():
    with TemporaryDirectory(prefix="legal-rag-smoke-") as directory:
        settings = Settings(data_dir=Path(directory))
        with fitz.open() as pdf:
            page = pdf.new_page()
            font = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
            vietnamese = font.exists()
            if vietnamese:
                page.insert_font(fontname="arial", fontfile=str(font))
                text = "Điều 1. Yêu cầu đối với ngân hàng.\n" + (
                    "Ngân hàng phải duy trì vốn phù hợp. Ngân hàng có trách nhiệm bảo mật thông tin khách hàng. " * 20)
                remaining = page.insert_textbox((50, 70, 545, 780), text, fontsize=11, fontname="arial")
            else:
                text = "A bank must maintain adequate capital. Banks protect customer information. " * 20
                remaining = page.insert_textbox((50, 70, 545, 780), text, fontsize=11)
            assert remaining >= 0, "Smoke document text did not fit on page"
            content = pdf.tobytes()
        with TestClient(create_app(settings)) as client:
            response = client.post("/documents", files={"file": ("smoke.pdf", content, "application/pdf")})
            assert response.status_code == 202, response.text
            document_id = response.json()["document"]["id"]
            deadline = time.monotonic() + 1800
            while time.monotonic() < deadline:
                document = client.get(f"/documents/{document_id}").json()
                if document["status"] in {"ready", "failed"}:
                    break
                time.sleep(0.5)
            assert document["status"] == "ready", document
            assert document["chunk_count"] > 1, document
            metadata = {'document_code':'SMOKE-ONLY', 'title':'Synthetic smoke PDF', 'version':'1',
                        'source_url':'https://example.org/synthetic.pdf', 'source_note':'Generated test, not law',
                        'validity_note':'No legal validity, test only', 'expected_revision':document['revision'],
                        'actor':'Smoke runner', 'reason':'Test review gate'}
            response = client.patch(f'/documents/{document_id}/metadata',json=metadata)
            assert response.status_code == 200,response.text
            response = client.post(f'/documents/{document_id}/review',json={
                'expected_revision':response.json()['revision'],'decision':'approved','actor':'Smoke runner','note':'Synthetic evidence only'})
            assert response.status_code == 200,response.text
            short_question = "Ngân hàng phải duy trì điều gì?" if vietnamese else "What must a bank maintain?"
            short = client.post("/search", json={"question": short_question, "document_ids": [document_id]})
            assert short.status_code == 200 and short.json()["sources"], short.text
            if vietnamese:
                assert short.json()["sources"][0]["article"] == "Điều 1"
            response = client.post("/search", json={"question": "Please review the following question carefully. " * 30 + short_question, "document_ids": [document_id], "max_distance": 2})
            assert response.status_code == 200, response.text
            sources = response.json()["sources"]
            assert sources and sources[0]["document_id"] == document_id and sources[0]["page"] == 1
            with fitz.open(stream=content, filetype='pdf') as pdf:
                for source in sources:
                    original = pdf[source['page']-1].get_text('text', sort=True)
                    assert original[source['start_char']:source['end_char']] == source['text']
                    assert source['sha256'] == document_id and source['review_status'] == 'approved'
            assert client.delete(f"/documents/{document_id}").status_code == 204
            assert client.post("/search", json={"question": "capital"}).json()["sources"] == []
            print({"status": "passed", "model": settings.embedding_model,
                   "chunk_count": document["chunk_count"], "retrieved": len(sources), "distance": sources[0]["distance"], "vietnamese_pdf": vietnamese,
                   "short_query_distance": short.json()["sources"][0]["distance"]})


if __name__ == "__main__":
    main()
