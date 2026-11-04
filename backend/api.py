from contextlib import asynccontextmanager
import hmac
import logging
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Path as PathParameter, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .legal import LegalMetadata, MetadataUpdate, ReviewRequest, RelationshipRequest
from .config import Settings
from .service import DocumentService, ServiceError


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    top_k: int = Field(default=5, ge=1, le=20)
    max_distance: float = Field(default=0.5, ge=0, le=2)

    @field_validator("question")
    @classmethod
    def clean_question(cls, value):
        if not value.strip():
            raise ValueError("Câu hỏi không được rỗng.")
        return value.strip()


class Document(LegalMetadata):
    id: str
    filename: str
    sha256: str
    size_bytes: int
    status: str
    page_count: int
    chunk_count: int
    error: str | None
    created_at: str
    updated_at: str
    family_id: str
    review_status: str
    reviewed_by: str
    reviewed_at: str | None
    review_note: str
    revision: int
    validity_status: str
    relationships: list[dict]


class UploadResult(BaseModel):
    document: Document
    duplicate: bool


class Source(BaseModel):
    citation_id: str
    chunk_id: str
    document_id: str
    filename: str
    page: int
    article: str
    clause: str
    point: str
    paragraph_id: str
    start_char: int
    end_char: int
    document_code: str
    version: str
    document_revision: int
    sha256: str
    review_status: str
    original_source_url: str
    effective_from: str | None
    effective_to: str | None
    validity_status: str
    text: str
    distance: float
    source_url: str


class SearchResult(BaseModel):
    sources: list[Source]


class Answer(BaseModel):
    answer: str
    citations: list[Source]
    claims: list[dict]
    insufficient_evidence: bool
    request_id: str
    warnings: list[str]


def create_app(settings=None, service=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        active = service or DocumentService(settings)
        active.start()
        app.state.service = active
        if not settings.api_key:
            logging.getLogger(__name__).warning("BACKEND_API_KEY is unset: local development mode; bind to loopback only.")
        try:
            yield
        finally:
            active.close()

    app = FastAPI(title="Legal RAG API", version="1.1.0", lifespan=lifespan,
                  description="Upload PDF, durable ingestion, vector retrieval and source-linked legal Q&A.")

    def authorize(x_api_key: Annotated[str | None, Header()] = None):
        if settings.api_key and (not x_api_key or not hmac.compare_digest(x_api_key.encode(), settings.api_key.encode())):
            raise HTTPException(401, "API key không hợp lệ.")

    def active(request: Request):
        return request.app.state.service

    @app.exception_handler(ServiceError)
    async def service_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/capabilities", dependencies=[Depends(authorize)])
    def capabilities():
        return {"generation_available": bool(settings.openai_api_key),
                "max_upload_bytes": settings.max_upload_bytes,
                "max_pdf_pages": settings.max_pages,
                "supported_extensions": ["pdf"]}

    @app.post("/documents", status_code=202, response_model=UploadResult, dependencies=[Depends(authorize)])
    def upload(response: Response, file: Annotated[UploadFile, File()],
               metadata: Annotated[str | None, Form()] = None, parent_id: str | None = None, svc=Depends(active)):
        try:
            parsed = LegalMetadata.model_validate_json(metadata) if metadata else LegalMetadata()
        except ValueError as exc:
            file.file.close()
            raise HTTPException(422, 'Metadata không hợp lệ: ' + str(exc)) from exc
        document, duplicate = svc.upload(file, parsed, parent_id)
        if duplicate:
            response.status_code = 200
        return {"document": document, "duplicate": duplicate}

    @app.get("/documents", response_model=list[Document], dependencies=[Depends(authorize)])
    def documents(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), svc=Depends(active)):
        return svc.list(limit, offset)

    @app.get("/documents/{document_id}", response_model=Document, dependencies=[Depends(authorize)])
    def document(document_id: str, svc=Depends(active)):
        return svc.get(document_id)

    @app.patch('/documents/{document_id}/metadata', response_model=Document, dependencies=[Depends(authorize)])
    def metadata(document_id: str, body: MetadataUpdate, svc=Depends(active)):
        return svc.edit_metadata(document_id, body)

    @app.post('/documents/{document_id}/review', response_model=Document, dependencies=[Depends(authorize)])
    def review(document_id: str, body: ReviewRequest, svc=Depends(active)):
        return svc.review(document_id, body)

    @app.get('/documents/{document_id}/versions', response_model=list[Document], dependencies=[Depends(authorize)])
    def versions(document_id: str, svc=Depends(active)):
        doc = svc.registry.get(document_id)
        if not doc:
            raise HTTPException(404, 'Không tìm thấy văn bản.')
        return [svc.describe(d) for d in svc.registry.versions(doc['family_id'])]

    @app.get('/documents/{document_id}/history', dependencies=[Depends(authorize)])
    def history(document_id: str, svc=Depends(active)):
        if not svc.registry.get(document_id):
            raise HTTPException(404, 'Không tìm thấy văn bản.')
        return svc.registry.history(document_id)

    @app.post('/documents/{document_id}/relationships', response_model=Document, dependencies=[Depends(authorize)])
    def add_relation(document_id: str, body: RelationshipRequest, svc=Depends(active)):
        return svc.add_relationship(document_id, body)

    @app.delete('/documents/{document_id}/relationships/{relation_id}', response_model=Document, dependencies=[Depends(authorize)])
    def remove_relation(document_id: str, relation_id: int, body: ReviewRequest, svc=Depends(active)):
        return svc.remove_relationship(document_id, relation_id, body)

    @app.get('/documents/{document_id}/chunks', dependencies=[Depends(authorize)])
    def chunks(document_id: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), svc=Depends(active)):
        svc.get(document_id)
        return [svc.evidence(document_id, c['chunk_id']) for c in svc.registry.chunks(document_id,limit,offset)]

    @app.get('/documents/{document_id}/chunks/{chunk_index}', dependencies=[Depends(authorize)])
    def chunk(document_id: str, chunk_index: int, svc=Depends(active)):
        return svc.evidence(document_id, f'{document_id}:{chunk_index}')

    @app.get("/documents/{document_id}/file", dependencies=[Depends(authorize)])
    def original(document_id: str, svc=Depends(active)):
        doc = svc.get(document_id)
        path = svc.files / f"{doc['id']}.pdf"
        if not path.is_file():
            raise HTTPException(404, "File gốc không còn tồn tại.")
        return FileResponse(path, media_type="application/pdf", filename=doc["filename"],
                            content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff"})

    @app.get("/documents/{document_id}/pages/{page_number}", dependencies=[Depends(authorize)])
    def document_page(document_id: str, page_number: Annotated[int, PathParameter(ge=1)], chunk_id: str | None = None, svc=Depends(active)):
        import pymupdf
        doc = svc.get(document_id)
        path = svc.files / f"{doc['id']}.pdf"
        if not path.is_file():
            raise HTTPException(404, "File gốc không còn tồn tại.")
        try:
            with pymupdf.open(path) as pdf:
                if page_number > pdf.page_count:
                    raise HTTPException(404, "Trang không tồn tại trong tài liệu.")
                page = pdf[page_number - 1]
                if chunk_id:
                    evidence = svc.evidence(document_id, chunk_id)
                    if evidence['page'] != page_number:
                        raise HTTPException(422, 'Đoạn nguồn không thuộc trang này.')
                    for rect in page.search_for(evidence['text']):
                        page.draw_rect(rect, color=None, fill=(1, .85, .15), fill_opacity=.3, overlay=True)
                scale = min(1.7, 2048 / max(page.rect.width, page.rect.height))
                pixels = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                return Response(pixels.tobytes("png"), media_type="image/png", headers={
                    "X-Page-Count": str(pdf.page_count), "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff"})
        except (pymupdf.FileDataError, RuntimeError) as exc:
            raise HTTPException(422, "Không thể hiển thị trang của tài liệu này.") from exc

    @app.post("/documents/{document_id}/retry", status_code=202, response_model=Document, dependencies=[Depends(authorize)])
    def retry(document_id: str, svc=Depends(active)):
        return svc.retry(document_id)

    @app.delete("/documents/{document_id}", status_code=204, dependencies=[Depends(authorize)])
    def delete(document_id: str, svc=Depends(active)):
        svc.delete(document_id)
        return Response(status_code=204)

    @app.post("/search", response_model=SearchResult, dependencies=[Depends(authorize)])
    def search(body: SearchRequest, svc=Depends(active)):
        return {"sources": svc.search(**body.model_dump())}

    @app.post("/ask", response_model=Answer, dependencies=[Depends(authorize)])
    def ask(body: SearchRequest, svc=Depends(active)):
        result = svc.ask(**body.model_dump())
        return {**result, "request_id": uuid4().hex,
                "warnings": ["Nguồn do người duyệt xác nhận; khoảng ngày ghi nhận không thay thế việc kiểm tra hiệu lực pháp lý. Câu trả lời dùng trích đoạn nguyên văn, không tự diễn giải."]}

    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    app.mount("/assets", StaticFiles(directory=frontend_dir / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def web_app():
        return FileResponse(frontend_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
