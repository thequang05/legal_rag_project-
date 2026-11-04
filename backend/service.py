import hashlib
import json
import unicodedata
import logging
import os
from pathlib import Path
import sqlite3
from datetime import date
from threading import Event, RLock, Thread
from uuid import uuid4

from filelock import FileLock
from .documents import Registry, now
from .legal import LegalMetadata, validity
from .parsing import validate_pdf, extract_chunks, build_contexts
from .lexical import LexicalIndex
from .vectors import VectorIndex
from .generation import AnswerGenerator

logger = logging.getLogger(__name__)


class ServiceError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class DocumentService:
    def __init__(self, settings, index=None, generator=None):
        self.settings = settings
        self.root = Path(settings.data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.files = self.root / "files"
        self.files.mkdir(exist_ok=True)
        self.registry = Registry(self.root / "registry.sqlite3")
        self.index = index or VectorIndex(self.root / "chroma", settings.embedding_model)
        self.lexical = LexicalIndex(self.registry)
        self.generator = generator or AnswerGenerator(settings.openai_api_key, settings.llm_model)
        self.lock = RLock()
        self.upload_lock = RLock()
        self.stop_event = Event()
        self.wake = Event()
        self.process_lock = FileLock(str(self.root / "backend.lock"), timeout=0)
        self.worker = None

    def start(self):
        self.process_lock.acquire()
        try:
            config_path = self.root / "index_config.json"
            config = {"embedding_model": self.settings.embedding_model, "chunk_schema": 5}
            if config_path.exists():
                previous = json.loads(config_path.read_text())
                if previous.get('embedding_model') != config['embedding_model'] or previous.get('chunk_schema') not in (2, 3, 4, 5):
                    raise RuntimeError("Embedding/chunk configuration changed. Use a new DATA_DIR and re-upload documents.")
                if previous.get('chunk_schema') in (2, 3, 4):
                    # Exact evidence offsets / contextual embeddings require re-indexing; keep PDFs and legal metadata.
                    for doc in self.registry.list(1000000):
                        if doc['status'] not in ('deleting',):
                            self.registry.update(doc['id'], status='queued', chunk_count=0, error=None)
            config_path.write_text(json.dumps(config))
            # Remove incomplete uploads from an interrupted request before accepting new ones.
            for path in self.files.glob("*.upload"):
                path.unlink(missing_ok=True)
            self.registry.recover()
            self.worker = Thread(target=self._run, name="document-ingestion", daemon=True)
            self.worker.start()
        except Exception:
            self.process_lock.release()
            raise

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.worker:
            self.worker.join()
        self.process_lock.release()

    def _run(self):
        while not self.stop_event.is_set():
            job = self.registry.next_job()
            if job:
                if job["status"] == "deleting":
                    try:
                        with self.lock:
                            current = self.registry.get(job['id'])
                            if current and current['status'] == 'deleting':
                                self.delete(job['id'])
                    except Exception:
                        logger.exception("Document cleanup failed: %s", job["id"])
                        self.wake.wait(2)
                        self.wake.clear()
                else:
                    self.process(job["id"])
            else:
                self.wake.wait(1)
                self.wake.clear()

    def upload(self, file, metadata=None, parent_id=None):
        filename = (file.filename or "").replace("\\", "/").split("/")[-1]
        filename = "".join(c for c in filename if c.isprintable())[:240]
        if not filename.lower().endswith(".pdf"):
            raise ServiceError(415, "Chỉ hỗ trợ file .pdf.")
        temporary = self.files / f"{uuid4().hex}.upload"
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("wb") as target:
                while block := file.file.read(1024 * 1024):
                    size += len(block)
                    if size > self.settings.max_upload_bytes:
                        raise ServiceError(413, "File vượt quá dung lượng cho phép.")
                    target.write(block)
                    digest.update(block)
            if size == 0:
                raise ServiceError(422, "File rỗng.")
            try:
                validate_pdf(temporary, self.settings.max_pages)
            except ValueError as exc:
                raise ServiceError(422, str(exc)) from exc
            document_id = digest.hexdigest()
            metadata = (metadata or LegalMetadata()).model_dump(mode='json')
            with self.lock, self.upload_lock:
                parent = self.get(parent_id) if parent_id else None
                family_id = parent['family_id'] if parent else document_id
                existing = self.registry.get(document_id)
                if existing:
                    if parent and existing['family_id'] != family_id:
                        raise ServiceError(409, 'Nội dung PDF đã tồn tại ở nhóm văn bản khác; không tự gán lại phiên bản.')
                    if parent and existing['version'] != metadata['version']:
                        raise ServiceError(409, 'Cùng nội dung PDF đã thuộc phiên bản khác; không tạo bản sao nội dung.')
                    if existing['status'] == 'deleting':
                        raise ServiceError(409, 'Phiên bản đang xóa; đợi hoàn tất trước khi nạp lại.')
                    if existing['status'] == 'deleted':
                        os.replace(temporary, self.files / f"{document_id}.pdf")
                        try:
                            self.registry.mutate(document_id, existing['revision'],
                                {'status':'queued', 'review_status':'draft', 'reviewed_by':'',
                                 'reviewed_at':None, 'review_note':'', 'error':None, 'chunk_count':0},
                                'restored', 'upload', 'Nạp lại đúng bytes, giữ ID/nhóm/metadata cũ, yêu cầu duyệt lại')
                        except Exception:
                            (self.files / f"{document_id}.pdf").unlink(missing_ok=True)
                            raise
                        self.wake.set()
                        return self.get(document_id), False
                    return self.describe(existing), True
                if parent and metadata['version'] in {d['version'] for d in self.registry.versions(family_id)}:
                    raise ServiceError(409, 'Phiên bản đã tồn tại trong nhóm văn bản. Chọn mã phiên bản khác.')
                os.replace(temporary, self.files / f"{document_id}.pdf")
                try:
                    document = self.registry.insert(document_id, filename, document_id, size, metadata, family_id)
                except Exception:
                    (self.files / f"{document_id}.pdf").unlink(missing_ok=True)
                    raise
            self.wake.set()
            return self.describe(document), False
        finally:
            temporary.unlink(missing_ok=True)
            file.file.close()

    def get(self, document_id):
        document = self.registry.get(document_id)
        if not document or document['status'] == 'deleted':
            raise ServiceError(404, "Không tìm thấy tài liệu hoặc phiên bản đã bị xóa.")
        return self.describe(document)

    def process(self, document_id):
        with self.lock:
            document = self.registry.get(document_id)
            if not document or document["status"] != "queued":
                return
            self.registry.update(document_id, status="processing", error=None, chunk_count=0)
            try:
                page_count, chunks = extract_chunks(self.files / f"{document_id}.pdf", self.settings.max_pages)
                chunks = self.index.prepare_chunks(chunks)
                if len(chunks) > self.settings.max_chunks:
                    raise ValueError("Tài liệu tạo quá nhiều chunk; hãy chia nhỏ file.")
                self.index.delete(document_id)
                self.index.add(document_id, document["filename"], chunks, build_contexts(chunks))
                self.registry.save_chunks(document_id, chunks)
                self.lexical.invalidate(document_id)
                self.registry.update(document_id, status="ready", page_count=page_count, chunk_count=len(chunks))
            except Exception as exc:
                logger.exception("Ingestion failed: %s", document_id)
                # Only ready documents are searchable, even if cleanup also fails.
                try:
                    self.index.delete(document_id)
                except Exception:
                    logger.exception("Partial index cleanup failed: %s", document_id)
                error = str(exc) if isinstance(exc, ValueError) else "Xử lý thất bại. Kiểm tra log backend rồi thử lại."
                self.registry.update(document_id, status="failed", error=error, chunk_count=0)

    def retry(self, document_id):
        with self.lock:
            document = self.get(document_id)
            if document["status"] != "failed":
                raise ServiceError(409, "Chỉ thử lại tài liệu đang ở trạng thái failed.")
            self.registry.update(document_id, status="queued", error=None)
        self.wake.set()
        return self.get(document_id)

    def delete(self, document_id):
        with self.lock, self.upload_lock:
            self.get(document_id)
            self.registry.update(document_id, status="deleting")
            try:
                self.index.delete(document_id)
                (self.files / f"{document_id}.pdf").unlink(missing_ok=True)
                self.registry.remove(document_id)
                self.lexical.invalidate(document_id)
            except Exception as exc:
                self.wake.set()
                raise ServiceError(503, "Đang chờ dọn dữ liệu; hệ thống sẽ tự thử lại.") from exc

    def describe(self, document):
        return {**document, 'validity_status': validity(document),
                'relationships': self.registry.relationships(document['id'])}

    def list(self, limit=100, offset=0):
        return [self.describe(doc) for doc in self.registry.list(limit, offset)]

    def edit_metadata(self, document_id, body):
        with self.lock:
            doc = self.get(document_id)
            changes = body.model_dump(mode='json', exclude_unset=True,
                                      exclude={'expected_revision', 'actor', 'reason'})
            try:
                values = LegalMetadata.model_validate({
                    **{name: doc[name] for name in LegalMetadata.model_fields},
                    **changes}).model_dump(mode='json')
            except ValueError as exc:
                raise ServiceError(422, str(exc)) from exc
            values.update(review_status='draft', reviewed_by='', reviewed_at=None, review_note='')
            return self._mutate(document_id, body.expected_revision, values, 'metadata_updated', body.actor, body.reason)

    def _mutate(self, document_id, revision, values, event, actor, reason, relationship=None):
        try:
            return self.describe(self.registry.mutate(document_id, revision, values, event, actor, reason, relationship))
        except (ValueError, sqlite3.IntegrityError) as exc:
            raise ServiceError(409, str(exc)) from exc

    def review(self, document_id, body):
        with self.lock:
            doc = self.get(document_id)
            if body.decision == 'approved':
                if doc['status'] != 'ready':
                    raise ServiceError(409, 'Chỉ duyệt được phiên bản đã xử lý thành công.')
                if not all(doc[key] for key in ('document_code', 'title', 'version', 'source_url', 'source_note', 'validity_note')):
                    raise ServiceError(422, 'Cần mã, tiêu đề, phiên bản, URL nguồn, căn cứ nguồn và ghi chú hiệu lực (kể cả khi chưa xác định ngày).')
                for relation in doc['relationships']:
                    if relation['source_id'] == document_id:
                        target = self.registry.get(relation['target_id'])
                        if not target or target['status'] == 'deleted':
                            raise ServiceError(409, 'Quan hệ trỏ tới phiên bản đã xóa; cần sửa quan hệ trước khi duyệt.')
            return self._mutate(document_id, body.expected_revision,
                {'review_status':body.decision, 'reviewed_by':body.actor, 'reviewed_at':now(), 'review_note':body.note},
                'review_' + body.decision, body.actor, body.note)

    def add_relationship(self, document_id, body):
        with self.lock:
            doc, target = self.get(document_id), self.get(body.target_id)
            if document_id == body.target_id:
                raise ServiceError(422, 'Không thể tự sửa đổi/thay thế chính phiên bản này.')
            # A directed cycle has no meaningful legal ordering, including mixed relation kinds.
            pending, visited = [target['id']], set()
            while pending:
                current = pending.pop()
                if current == document_id:
                    raise ServiceError(409, 'Quan hệ tạo vòng lặp sửa đổi/thay thế.')
                if current in visited:
                    continue
                visited.add(current)
                pending.extend(r['target_id'] for r in self.registry.relationships(current) if r['source_id'] == current)
            relation = body.model_dump(mode='json', exclude={'expected_revision', 'actor'})
            return self._mutate(doc['id'], body.expected_revision,
                {'review_status':'draft', 'reviewed_at':None, 'reviewed_by':'', 'review_note':''},
                'relationship_added',body.actor,body.note,relation)

    def remove_relationship(self, document_id, relation_id, body):
        with self.lock:
            self.get(document_id)
            with self.registry.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT revision FROM documents WHERE id=?',(document_id,)).fetchone()
                if current['revision'] != body.expected_revision:
                    raise ServiceError(409, 'Dữ liệu đã thay đổi. Tải lại trước khi lưu.')
                relation = db.execute('SELECT * FROM relationships WHERE id=? AND source_id=?',(relation_id,document_id)).fetchone()
                if not relation:
                    raise ServiceError(404,'Không tìm thấy quan hệ đi ra từ phiên bản này.')
                db.execute('DELETE FROM relationships WHERE id=?',(relation_id,))
                db.execute("UPDATE documents SET revision=revision+1,review_status='draft',reviewed_by='',reviewed_at=NULL,review_note='',updated_at=? WHERE id=?",(now(),document_id))
                self.registry._record(db,document_id,'relationship_removed',body.actor,body.note)
            return self.get(document_id)

    def evidence(self, document_id, chunk_id):
        doc = self.get(document_id)
        chunk = self.registry.chunk(chunk_id)
        if not chunk or chunk['document_id'] != document_id or doc['status'] != 'ready':
            raise ServiceError(404, 'Đoạn nguồn không tồn tại trong phiên bản đã xử lý này.')
        return {**chunk, 'filename':doc['filename'], 'document_code':doc['document_code'],
                'version':doc['version'], 'document_revision':doc['revision'], 'sha256':doc['sha256'],
                'review_status':doc['review_status'], 'original_source_url':doc['source_url'],
                'effective_from':doc['effective_from'], 'effective_to':doc['effective_to'],
                'validity_status':doc['validity_status'],
                'source_url':f"/documents/{document_id}/file#page={chunk['page']}"}

    def search(self, question, document_ids, top_k, max_distance):
        with self.lock:
            ready = set(self.registry.ready_ids())
            if document_ids:
                for document_id in document_ids:
                    document = self.get(document_id)
                    if document['status'] != 'ready' or document['review_status'] != 'approved':
                        raise ServiceError(409, 'Phiên bản chưa xử lý xong hoặc chưa được duyệt nguồn.')
                ready &= set(document_ids)
            scope = sorted(ready)
            pool = max(top_k * 3, 20)
            try:
                vector_hits = self.index.search(question, scope, pool)
                lexical_ids = self.lexical.search(question, scope, pool)
                vector_ids = {hit['chunk_id'] for hit in vector_hits}
                lexical_only = [chunk_id for chunk_id in lexical_ids if chunk_id not in vector_ids]
                extra = self.index.distances(question, lexical_only)
            except Exception as exc:
                logger.exception('Search failed')
                raise ServiceError(503, 'Tìm kiếm tạm thời không khả dụng.') from exc
            # Reciprocal rank fusion of vector and keyword (BM25) rankings; max_distance still gates every hit.
            score = {}
            for rank, chunk_id in enumerate([hit['chunk_id'] for hit in vector_hits]):
                score[chunk_id] = score.get(chunk_id, 0.0) + 1 / (60 + rank)
            for rank, chunk_id in enumerate(lexical_ids):
                score[chunk_id] = score.get(chunk_id, 0.0) + 1 / (60 + rank)
            candidates = {hit['chunk_id']: hit for hit in vector_hits}
            for chunk_id, distance in extra.items():
                candidates[chunk_id] = {'chunk_id': chunk_id, 'document_id': chunk_id.rsplit(':', 1)[0],
                                        'distance': distance, 'text': None}
            sources = []
            for chunk_id in sorted(candidates, key=lambda c: (-score[c], c)):
                hit = candidates[chunk_id]
                # A keyword match is evidence of relevance the embedding may miss, so it gets a looser semantic gate.
                limit = max_distance if hit['text'] is not None else min(max_distance + self.LEXICAL_DISTANCE_MARGIN, 2)
                if hit['document_id'] not in ready or hit['distance'] > limit:
                    continue
                evidence = self.evidence(hit['document_id'], hit['chunk_id'])
                # SQLite evidence is authoritative; never expose a stale vector payload.
                if hit['text'] is not None and evidence['text'] != hit['text']:
                    continue
                sources.append({**evidence, 'citation_id':str(len(sources)+1), 'distance':hit['distance']})
                if len(sources) == top_k:
                    break
            return sources

    LEXICAL_DISTANCE_MARGIN = 0.2
    EXPAND_RADIUS = 12
    MAX_EVIDENCE = 60

    def _expand(self, sources):
        """Add the Khoản/Điểm siblings and Điều heading around each hit so the model sees whole lists.

        Only real stored chunks are added, so quote verification is unchanged.
        """
        selected = {}
        def key(chunk):
            return chunk['document_id'], int(chunk['chunk_id'].rsplit(':', 1)[1])
        for source in sources:
            doc_id, index = key(source)
            window = self.registry.chunk_range(doc_id, index - self.EXPAND_RADIUS, index + self.EXPAND_RADIUS + 1)
            by_index = {key(c)[1]: c for c in window}
            article, clause = source.get('article', ''), source.get('clause', '')
            keep = {index}
            if article:
                if clause:
                    same = lambda c: c.get('article') == article and c.get('clause') == clause
                    for step in (-1, 1):
                        k = index + step
                        while k in by_index and same(by_index[k]):
                            keep.add(k); k += step
                    before = by_index.get(min(keep) - 1)
                    if before and before.get('article') == article and not before.get('clause'):
                        keep.add(min(keep) - 1)
                else:
                    k = index + 1
                    while k in by_index and by_index[k].get('article') == article:
                        keep.add(k); k += 1
            for k in sorted(keep):
                chunk = by_index[k]
                selected.setdefault(key(chunk), (chunk, source['distance']))
        merged = []
        for _, (chunk, distance) in sorted(selected.items())[:self.MAX_EVIDENCE]:
            evidence = {**self.evidence(chunk['document_id'], chunk['chunk_id']), 'distance': distance}
            if merged and self._continues(merged[-1], evidence):
                last = merged[-1]
                last['text'] += evidence['text'][last['end_char'] - evidence['start_char']:]
                last['end_char'] = evidence['end_char']
            else:
                merged.append(evidence)
        return [{**e, 'citation_id': str(position)} for position, e in enumerate(merged, start=1)]

    @staticmethod
    def _continues(previous, chunk):
        """True when chunk is the overlapping tail of the same clause piece split by the embedding limit."""
        if any(previous.get(k) != chunk.get(k) for k in ('document_id', 'page', 'article', 'clause', 'point')):
            return False
        overlap = previous['end_char'] - chunk['start_char']
        return 0 < overlap < len(chunk['text']) and previous['text'].endswith(chunk['text'][:overlap])

    @staticmethod
    def _fold(text):
        """Whitespace-collapsed, diacritic-free characters, each with its index in `text`."""
        folded, positions = [], []
        for index, char in enumerate(text):
            if char.isspace():
                if folded and folded[-1] != ' ':
                    folded.append(' '); positions.append(index)
                continue
            base = 'd' if char in 'đĐ' else ''.join(c for c in unicodedata.normalize('NFD', char) if not unicodedata.combining(c))
            for c in ('D' if char == 'Đ' else base):
                folded.append(c); positions.append(index)
        return ''.join(folded), positions

    @staticmethod
    def _verbatim(quote, text):
        """Exact source span matching quote modulo whitespace and diacritics, else None.

        The model only locates the span; the returned string is always the source's own text,
        so a copy slip such as 'dang' for 'đang' cannot put unverified words in the answer.
        """
        wanted, _ = DocumentService._fold(quote)
        wanted = wanted.strip()
        if not wanted:
            return None
        folded, positions = DocumentService._fold(text)
        start = folded.find(wanted)
        if start < 0:
            return None
        return text[positions[start]:positions[start + len(wanted) - 1] + 1]

    def ask(self, question, document_ids, top_k, max_distance):
        sources = self.search(question, document_ids, top_k, max_distance)
        if sources:
            with self.lock:
                sources = self._expand(sources)
        refusal = {'answer':'Chưa đủ thông tin trong tài liệu đã duyệt để trả lời câu hỏi này.',
                   'citations':[], 'claims':[], 'insufficient_evidence':True}
        if not sources:
            return refusal
        try:
            result = self.generator.answer(question, sources)
            if result['insufficient_evidence']:
                return refusal
            known = {s['citation_id']:s for s in sources}
            claims = result.get('claims', [])
            if not claims or len(claims) > 20:
                return refusal
            checked = []
            for claim in claims:
                source = known.get(claim.get('citation_id'))
                quote = claim.get('quote', '')
                exact = self._verbatim(quote, source['text']) if source and isinstance(quote,str) else None
                if exact is None:
                    logger.warning('Rejected answer with non-verbatim evidence: citation=%s quote=%.160r', claim.get('citation_id'), quote)
                    return refusal
                quote = exact
                checked.append({'citation_id':source['citation_id'], 'quote':quote})
            with self.lock:
                for source in sources:
                    current = self.get(source['document_id'])
                    if current['review_status'] != 'approved' or current['revision'] != source['document_revision'] or current['status'] != 'ready':
                        return refusal
            used = list(dict.fromkeys(c['citation_id'] for c in checked))
            # Only validated quotations become conclusions. No unsupported model prose is rendered.
            answer = '\n\n'.join(f"Theo tài liệu: «{c['quote']}» [{c['citation_id']}]" for c in checked)
            return {'answer':answer, 'claims':checked, 'citations':[known[c] for c in used], 'insufficient_evidence':False}
        except ServiceError:
            return refusal
        except RuntimeError as exc:
            raise ServiceError(503, str(exc)) from exc
        except Exception as exc:
            logger.exception('Answer generation failed')
            raise ServiceError(502, 'Nhà cung cấp LLM không trả về câu trả lời hợp lệ.') from exc
