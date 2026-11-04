"""Durable registry, immutable PDF versions, evidence and metadata history."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3


def now():
    return datetime.now(timezone.utc).isoformat()


class Registry:
    def __init__(self, path):
        self.path = path
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('''CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL, status TEXT NOT NULL,
                page_count INTEGER NOT NULL DEFAULT 0, chunk_count INTEGER NOT NULL DEFAULT 0,
                error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(documents)')}
            additions = {
                'family_id': "TEXT NOT NULL DEFAULT ''", 'document_code': "TEXT NOT NULL DEFAULT ''",
                'title': "TEXT NOT NULL DEFAULT ''", 'version': "TEXT NOT NULL DEFAULT '1'",
                'source_url': "TEXT NOT NULL DEFAULT ''", 'source_note': "TEXT NOT NULL DEFAULT ''",
                'effective_from': 'TEXT', 'effective_to': 'TEXT', 'validity_note': "TEXT NOT NULL DEFAULT ''",
                'review_status': "TEXT NOT NULL DEFAULT 'draft'", 'reviewed_by': "TEXT NOT NULL DEFAULT ''",
                'reviewed_at': 'TEXT', 'review_note': "TEXT NOT NULL DEFAULT ''",
                'revision': 'INTEGER NOT NULL DEFAULT 1'}
            for name, definition in additions.items():
                if name not in columns:
                    db.execute(f'ALTER TABLE documents ADD COLUMN {name} {definition}')
            db.execute("UPDATE documents SET family_id=id WHERE family_id=''")
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS family_version ON documents(family_id, version)')
            db.execute('''CREATE TABLE IF NOT EXISTS history (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL,
                event TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL,
                at TEXT NOT NULL, snapshot TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, target_id TEXT NOT NULL,
                kind TEXT NOT NULL, effective_on TEXT, note TEXT NOT NULL,
                UNIQUE(source_id,target_id,kind))''')
            db.execute('''CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, document_id TEXT NOT NULL, content TEXT NOT NULL)''')

    @contextmanager
    def connection(self):
        with sqlite3.connect(self.path, timeout=30) as db:
            db.row_factory = sqlite3.Row
            yield db

    def get(self, document_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit=100, offset=0):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM documents WHERE status!='deleted' ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))]

    def _record(self, db, document_id, event, actor, reason):
        doc = dict(db.execute('SELECT * FROM documents WHERE id=?', (document_id,)).fetchone())
        relations = [dict(r) for r in db.execute('SELECT * FROM relationships WHERE source_id=? OR target_id=?', (document_id, document_id))]
        db.execute('INSERT INTO history(document_id,event,actor,reason,at,snapshot) VALUES(?,?,?,?,?,?)',
                   (document_id, event, actor, reason, now(), json.dumps({'document': doc, 'relationships': relations}, ensure_ascii=False)))

    def insert(self, document_id, filename, digest, size, metadata=None, family_id=None):
        with self.connection() as db:
            values = {'id': document_id, 'filename': filename, 'sha256': digest,
                      'size_bytes': size, 'status': 'queued', 'created_at': now(),
                      'updated_at': now(), 'family_id': family_id or document_id, **(metadata or {})}
            keys = ','.join(values)
            db.execute(f"INSERT INTO documents ({keys}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))
            self._record(db, document_id, 'uploaded', 'upload', 'PDF mới, chờ duyệt nguồn')
        return self.get(document_id)

    def update(self, document_id, **values):
        if not values or not set(values) <= {'status', 'page_count', 'chunk_count', 'error'}:
            raise ValueError('Invalid registry update')
        values['updated_at'] = now()
        assignments = ', '.join(f'{key}=?' for key in values)
        with self.connection() as db:
            db.execute(f'UPDATE documents SET {assignments} WHERE id=?', (*values.values(), document_id))

    def mutate(self, document_id, expected_revision, values, event, actor, reason, relationship=None):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT revision FROM documents WHERE id=?', (document_id,)).fetchone()
            if not current or current['revision'] != expected_revision:
                raise ValueError('Dữ liệu đã thay đổi. Tải lại trước khi lưu.')
            values = {**values, 'revision': expected_revision + 1, 'updated_at': now()}
            assignments = ', '.join(f'{key}=?' for key in values)
            db.execute(f'UPDATE documents SET {assignments} WHERE id=?', (*values.values(), document_id))
            if relationship:
                db.execute('''INSERT INTO relationships(source_id,target_id,kind,effective_on,note) VALUES(?,?,?,?,?)''',
                           (document_id, relationship['target_id'], relationship['kind'], relationship['effective_on'], relationship['note']))
            self._record(db, document_id, event, actor, reason)
        return self.get(document_id)

    def history(self, document_id):
        with self.connection() as db:
            return [{**dict(row), 'snapshot': json.loads(row['snapshot'])} for row in db.execute(
                'SELECT * FROM history WHERE document_id=? ORDER BY sequence DESC', (document_id,))]

    def relationships(self, document_id):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM relationships WHERE source_id=? OR target_id=? ORDER BY id', (document_id,document_id))]

    def versions(self, family_id):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM documents WHERE family_id=? ORDER BY created_at', (family_id,))]

    def save_chunks(self, document_id, chunks):
        with self.connection() as db:
            db.execute('DELETE FROM chunks WHERE document_id=?', (document_id,))
            db.executemany('INSERT INTO chunks(id,document_id,content) VALUES(?,?,?)', [
                (f'{document_id}:{i}',document_id,json.dumps(chunk,ensure_ascii=False)) for i,chunk in enumerate(chunks)])

    def chunk(self, chunk_id):
        with self.connection() as db:
            row = db.execute('SELECT * FROM chunks WHERE id=?', (chunk_id,)).fetchone()
        return {'chunk_id': row['id'], 'document_id':row['document_id'], **json.loads(row['content'])} if row else None

    def all_chunks(self, document_id):
        with self.connection() as db:
            rows = db.execute('SELECT * FROM chunks WHERE document_id=? ORDER BY rowid', (document_id,)).fetchall()
        return [{'chunk_id': row['id'], 'document_id': row['document_id'], **json.loads(row['content'])} for row in rows]

    def chunk_range(self, document_id, start, end):
        """Chunks with index in [start, end), in document order."""
        ids = [f'{document_id}:{i}' for i in range(max(start, 0), end)]
        if not ids:
            return []
        with self.connection() as db:
            rows = db.execute(f"SELECT * FROM chunks WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()
        by_id = {row['id']: {'chunk_id': row['id'], 'document_id': row['document_id'], **json.loads(row['content'])} for row in rows}
        return [by_id[i] for i in ids if i in by_id]

    def chunks(self, document_id, limit=100, offset=0):
        with self.connection() as db:
            return [self.chunk(row[0]) for row in db.execute('SELECT id FROM chunks WHERE document_id=? ORDER BY rowid LIMIT ? OFFSET ?', (document_id,limit,offset))]

    def remove(self, document_id):
        # Keep metadata/relationships/history as a tombstone; never retarget an old citation.
        with self.connection() as db:
            db.execute("UPDATE documents SET status='deleted',review_status='draft',revision=revision+1,updated_at=? WHERE id=?", (now(),document_id))
            db.execute('DELETE FROM chunks WHERE document_id=?',(document_id,))
            self._record(db, document_id, 'deleted', 'api', 'Xóa đúng bản PDF và vector; giữ lịch sử')

    def recover(self):
        with self.connection() as db:
            db.execute("UPDATE documents SET status='queued', updated_at=? WHERE status='processing'", (now(),))

    def next_job(self):
        with self.connection() as db:
            row = db.execute("SELECT id, status FROM documents WHERE status IN ('queued', 'deleting') ORDER BY created_at LIMIT 1").fetchone()
        return dict(row) if row else None

    def ready_ids(self):
        with self.connection() as db:
            return [row[0] for row in db.execute("SELECT id FROM documents WHERE status='ready' AND review_status='approved'")]
