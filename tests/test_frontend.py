from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from backend.api import create_app
from backend.config import Settings


def test_frontend_and_assets_are_served_without_exposing_project_files():
    with TemporaryDirectory() as directory:
        with TestClient(create_app(Settings(data_dir=Path(directory)))) as client:
            home = client.get('/')
            assert home.status_code == 200
            assert '<html lang="vi">' in home.text and '/assets/app.js' in home.text
            assert 'text/html' in home.headers['content-type']
            for asset in ['app.js', 'api.js', 'styles.css']:
                assert client.get('/assets/' + asset).status_code == 200
            assert client.get('/.env').status_code == 404
            assert client.get('/assets/%2e%2e/.env').status_code == 404
            assert client.get('/assets/__init__.py').status_code == 404
            assert client.get('/docs').status_code == 200


def test_capabilities_are_authenticated_and_never_contain_keys(tmp_path):
    settings = Settings(data_dir=tmp_path, api_key='backend-secret', openai_api_key='provider-secret')
    with TestClient(create_app(settings)) as client:
        assert client.get('/capabilities').status_code == 401
        response = client.get('/capabilities', headers={'X-API-Key': 'backend-secret'})
        assert response.status_code == 200
        assert response.json()['generation_available'] is True
        assert response.json()['max_upload_bytes'] == settings.max_upload_bytes
        assert 'secret' not in response.text


def test_pdf_page_preview_is_authenticated_and_bounded(tmp_path):
    import pymupdf
    from backend.service import DocumentService
    from test_api import TestIndex, Generator, pdf_bytes, wait_status
    settings = Settings(data_dir=tmp_path, api_key='secret')
    service = DocumentService(settings, index=TestIndex(tmp_path / 'chroma', 'test'), generator=Generator())
    with TestClient(create_app(settings, service)) as client:
        client.headers['X-API-Key'] = 'secret'
        uploaded = client.post('/documents', files={'file': ('law.pdf', pdf_bytes(pages=2), 'application/pdf')})
        doc_id = uploaded.json()['document']['id']
        wait_status(client, doc_id)
        response = client.get(f'/documents/{doc_id}/pages/2')
        assert response.status_code == 200
        assert response.headers['X-Page-Count'] == '2'
        assert response.content.startswith(b'\x89PNG')
        image = pymupdf.Pixmap(response.content)
        assert max(image.width, image.height) <= 2049
        assert client.get(f'/documents/{doc_id}/pages/3').status_code == 404
        assert client.get(f'/documents/{doc_id}/pages/0').status_code == 422
        client.headers.clear()
        assert client.get(f'/documents/{doc_id}/pages/1').status_code == 401
