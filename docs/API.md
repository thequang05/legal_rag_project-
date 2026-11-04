# Legal RAG API và vận hành

Các lệnh dưới đây chạy từ thư mục gốc project. Giao diện chính: <http://127.0.0.1:8000/>.

Backend FastAPI cho upload PDF → trích xuất theo trang → chia chunk → embedding → ChromaDB → hỏi đáp có nguồn. Không cần đặt sẵn một file luật cố định.

## Chạy local

Python 3.11–3.12 được khuyến nghị (đã kiểm thử với 3.12).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env
# Điền OPENAI_API_KEY trong .env nếu muốn dùng /ask.
uvicorn backend.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Mở giao diện tại <http://127.0.0.1:8000/> hoặc Swagger UI: <http://127.0.0.1:8000/docs>. Upload, tra trạng thái, tìm kiếm và xem file không cần OpenAI key. `/ask` cần key khi có nguồn phù hợp. Lần ingestion đầu tiên tải model embedding từ Hugging Face; cần Internet hoặc cache model sẵn. Có thể đặt `EMBEDDING_MODEL` thành đường dẫn model local.

Đặt `BACKEND_API_KEY` để bảo vệ mọi endpoint dữ liệu bằng header `X-API-Key`. Nếu bỏ trống, API ở chế độ phát triển local. `/`, `/assets`, `/health`, `/docs`, `/openapi.json` công khai và không chứa tài liệu. Không có CORS mở mặc định. Trước khi đưa ra mạng cần HTTPS/reverse proxy và giới hạn request tại gateway. Shared API key hiện áp dụng cho toàn kho, chưa có SSO, quyền từng tài liệu hoặc nhiều tenant.

## Docker

```bash
cp -n .env.example .env
# Điền key theo nhu cầu.
docker compose up --build -d
```

Port được bind localhost. Named volume `legal_data` giữ PDF, SQLite, Chroma và cache model sau khi container khởi động lại. `docker compose down` giữ dữ liệu; `down -v` sẽ xóa volume. Container chạy user không phải root. Không đưa `.env` hoặc dữ liệu vào image.

**Một process / một replica cho mỗi DATA_DIR.** File lock từ chối process thứ hai để tránh tranh chấp hàng đợi và Chroma local. Không dùng `--workers 2` hoặc nhiều replica chung volume. Ingestion tuần tự; search/delete chờ tác vụ ingestion đang chạy để không thấy index dở dang. Health và xem trạng thái vẫn hoạt động. Muốn mở rộng cần tách worker/queue và vector server.

## API

| Method | Endpoint | Chức năng |
|---|---|---|
| GET | `/` | Giao diện web |
| GET | `/capabilities` | Tính năng AI và giới hạn upload; không trả key |
| GET | `/health` | Liveness của HTTP service; không chứng minh LLM/model sẵn sàng |
| POST | `/documents` | Upload multipart field `file`; 202 cho file mới, 200 nếu trùng SHA-256 |
| GET | `/documents?limit=100&offset=0` | Danh sách tài liệu và trạng thái |
| GET | `/documents/{id}` | Chi tiết / theo dõi xử lý |
| GET | `/documents/{id}/file` | PDF gốc; dùng fragment `#page=N` ở PDF viewer |
| GET | `/documents/{id}/pages/{page}` | Trang PDF được render thành PNG, page bắt đầu từ 1; query chunk_id để đánh dấu đoạn |
| POST | `/documents/{id}/retry` | Thử lại tài liệu `failed` |
| DELETE | `/documents/{id}` | Xóa PDF/vector/đoạn của đúng phiên bản, giữ tombstone và lịch sử; 204 khi xong |
| POST | `/search` | Tìm chunk, không gọi LLM |
| POST | `/ask` | Trả lời bằng các quote nguyên văn đã kiểm tra với đoạn nguồn |
| PATCH | `/documents/{id}/metadata` | Sửa hồ sơ, cần expected_revision/actor/reason, reset chờ duyệt |
| POST | `/documents/{id}/review` | Quyết định approved/rejected/draft, cần expected_revision/actor/note |
| GET | `/documents/{id}/versions` | Các bản cùng family_id, gồm tombstone đã xóa |
| GET | `/documents/{id}/history` | Snapshot lịch sử hồ sơ/duyệt/quan hệ/xóa |
| POST | `/documents/{id}/relationships` | Thêm quan hệ amends/replaces với target_id, effective_on, note, actor, expected_revision |
| DELETE | `/documents/{id}/relationships/{relation_id}` | Gỡ quan hệ đi ra, JSON expected_revision/actor/note/decision=draft |
| GET | `/documents/{id}/chunks?limit=100&offset=0` | Đoạn gốc có trang, cấu trúc và offsets, có phân trang |
| GET | `/documents/{id}/chunks/{index}` | Đối chiếu một đoạn theo chỉ số chunk |

Upload bản mới trong một nhóm: `POST /documents?parent_id=ID_BAN_CU`, multipart `file` và `metadata` là chuỗi JSON, ví dụ `{"version":"2","document_code":"...","title":"..."}`. Bản mới cần hồ sơ và duyệt riêng. Không truyền parent_id sẽ tạo nhóm mới.

Ví dụ (bỏ header nếu không đặt `BACKEND_API_KEY`):

```bash
curl -X POST http://127.0.0.1:8000/documents \
  -H 'X-API-Key: YOUR_BACKEND_KEY' \
  -F 'file=@/absolute/path/law.pdf'

curl http://127.0.0.1:8000/documents/DOCUMENT_ID \
  -H 'X-API-Key: YOUR_BACKEND_KEY'

# Cập nhật hồ sơ và duyệt nguồn qua UI hoặc API trước khi tìm kiếm.
# Cần status=ready và review_status=approved.
curl -X POST http://127.0.0.1:8000/search \
  -H 'X-API-Key: YOUR_BACKEND_KEY' -H 'Content-Type: application/json' \
  -d '{"question":"Điều kiện cấp giấy phép là gì?","document_ids":["DOCUMENT_ID"],"top_k":5,"max_distance":0.5}'

curl -X POST http://127.0.0.1:8000/ask \
  -H 'X-API-Key: YOUR_BACKEND_KEY' -H 'Content-Type: application/json' \
  -d '{"question":"Điều kiện cấp giấy phép là gì?","document_ids":["DOCUMENT_ID"]}'
```

`document_ids=[]` hoặc không truyền: tìm trong tất cả tài liệu `ready` và `approved`. Nếu chỉ định tài liệu chưa xử lý hoặc chưa duyệt: 409; không tồn tại: 404. `top_k` từ 1–20. `max_distance` là khoảng cách cosine tối đa (0–2), **không phải xác suất hay độ tin cậy pháp lý**. Mặc định 0.5 là cấu hình ban đầu, cần hiệu chỉnh bằng bộ câu hỏi có nguồn chuẩn. Câu hỏi dài được chia theo giới hạn token, gộp trung bình các vector rồi chuẩn hóa; chưa có bước phân rã câu hỏi bằng LLM.

Ví dụ cấu trúc `/ask`:

```json
{
  "answer": "Theo tài liệu: «Đoạn văn bản gốc...» [1]",
  "claims": [{"citation_id":"1", "quote":"Đoạn văn bản gốc..."}],
  "citations": [{
    "citation_id": "1",
    "chunk_id": "<sha256>:0",
    "document_id": "<sha256>",
    "filename": "law.pdf",
    "page": 2,
    "article": "Điều 1",
    "clause":"1", "point":"", "paragraph_id":"p2:100",
    "start_char":100, "end_char":120,
    "document_code":"CODE", "version":"1", "document_revision":3,
    "sha256":"<sha256>", "review_status":"approved",
    "original_source_url":"https://example.org/source.pdf",
    "effective_from":null, "effective_to":null, "validity_status":"unknown",
    "text": "Đoạn văn bản gốc...",
    "distance": 0.2,
    "source_url": "/documents/<sha256>/file#page=2"
  }],
  "insufficient_evidence": false,
  "request_id": "...",
  "warnings": ["Nguồn do người duyệt xác nhận; khoảng ngày ghi nhận không thay thế việc kiểm tra hiệu lực pháp lý. Câu trả lời dùng trích đoạn nguyên văn, không tự diễn giải."]
}
```

Citation là đường dẫn tương đối. Client có API key cần tải file bằng request có header, rồi hiển thị/download; click link trực tiếp không tự thêm header. Hệ thống kiểm tra từng claim có quote nguyên văn khớp nguồn và tự dựng answer từ các quote. Không có lời diễn giải tự do của model trong answer. Kiểm tra lại revision/duyệt sau khi model trả về. Khi không có nguồn, quote sai hoặc nguồn thay đổi, trả chưa đủ thông tin. Thiếu OpenAI key khi cần chọn căn cứ: 503; lỗi nhà cung cấp/response: 502. Chi tiết quy tắc và giới hạn: [P0.md](P0.md).

## Dữ liệu và trạng thái

```text
DATA_DIR/                  # mặc định ./data/backend, tách khỏi DB demo cũ
├── files/<sha256>.pdf     # PDF gốc, không dùng tên upload làm đường dẫn
├── registry.sqlite3       # metadata, duyệt, quan hệ, lịch sử, đoạn gốc + hàng đợi bền vững
├── chroma/                # chunk, embedding, document_id, filename, page, article
├── index_config.json      # chặn đổi model trên kho hiện có
└── backend.lock
```

- Luồng: `queued → processing → ready` hoặc `failed`.
- SHA-256 toàn file là ID; upload cùng bytes trả bản đã có, không xử lý lại. Hai file khác nhau có namespace chunk khác nhau.
- File thay đổi cần nạp bản mới với parent_id và metadata.version để cùng nhóm; không ghi đè file gốc. Hồ sơ có quan hệ sửa đổi/thay thế và quyết định duyệt. Xem [P0.md](P0.md).
- Sau restart, `processing` chuyển về `queued`; worker xóa chunk dở trước khi nạp lại. Chỉ tài liệu `ready` và `approved` được tìm kiếm.
- Xóa giữ tombstone `deleted` và lịch sử sau khi dọn PDF/vector/đoạn. Dùng trạng thái `deleting`; nếu gián đoạn, worker tiếp tục dọn sau restart. Không trả chunk đang xóa.
- PDF lỗi, mã hóa có mật khẩu, rỗng hoặc quá số trang bị từ chối. Nếu có trang không trích được text, ingestion thất bại và báo cần OCR; chưa tích hợp OCR.
- Không cắt lề cố định hoặc loại bỏ đoạn ngắn. Chunk sơ bộ tối đa khoảng 700 ký tự, overlap 100; sau đó chia tiếp theo giới hạn token của model để tránh âm thầm cắt mất nội dung khi embedding. Giữ offsets nguyên văn, số trang PDF 1-based và Điều/Khoản/Điểm theo heading đầu dòng. Chưa có parser tổng quát cho Chương, bảng hoặc tài liệu nhiều cột; người duyệt cần đối chiếu cấu trúc nhận diện.
- `filename` là tên file, không phải tên pháp lý được xác minh. Không tự xác nhận nguồn chính thức, hiệu lực hoặc quan hệ sửa đổi/thay thế.
- Đổi model embedding: dùng `DATA_DIR` mới và nạp lại tài liệu. Không trộn vector khác model trong cùng kho.
- Backup: dừng service rồi sao lưu toàn DATA_DIR/volume (SQLite + Chroma + PDF cùng thời điểm). Khôi phục nguyên kho rồi khởi động lại.

## Giao diện và CLI

`python app.py` chạy FastAPI và frontend cùng cổng 8000. Frontend không cần Streamlit hoặc npm build. `python -m clients.cli` hoặc `python main.py` chạy client dòng lệnh khi backend đã hoạt động.

CLI đọc `BACKEND_URL` (mặc định `http://127.0.0.1:8000`) và `BACKEND_API_KEY`. Browser dùng cùng origin với giao diện; Backend API key nhập trong Cài đặt kết nối chỉ giữ trong bộ nhớ.

Code Streamlit, notebook và pipeline ban đầu đã chuyển vào `experiments/`. Không dùng các script lịch sử này để đánh giá kho backend mới. Chưa có dữ liệu luật hoặc benchmark pháp lý đi kèm repo.

## Kiểm thử

```bash
pip install -r requirements-dev.txt
pytest -q
```

Integration tests tạo PDF thật và dùng Chroma persistent thật; embedding xác định và generator giả lập để chạy offline, không phát sinh phí LLM. Bao phủ upload, dedup, nhiều tài liệu, nguồn trang, tìm kiếm có filter, hỏi đáp, citation sai, xóa, lỗi ingestion/retry, phục hồi sau restart, giới hạn upload, auth. Chất lượng embedding/LLM trên tài liệu luật thật cần kiểm thử riêng với dữ liệu chuẩn.

## Tài liệu kỹ thuật

- [FastAPI file uploads](https://fastapi.tiangolo.com/tutorial/request-files/)
- [Chroma Python client](https://docs.trychroma.com/reference/python)
- [OpenAI Docs — Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

Nếu mạng không ổn định, tải sẵn model bằng công cụ giữ file dở và kiểm tra SHA-256:

```bash
python -m scripts.prefetch_model
```

Công cụ dùng cache `HF_HOME` (mặc định `./data/model-cache`), giữ file `.resume` khi mất kết nối và dùng HTTP Range để tiếp tục. Cấu hình/tokenizer được tải từ cùng revision với trọng số. Sau khi đã tải xong, có thể chạy với `HF_HUB_OFFLINE=1`.

Smoke test model embedding thật (lần đầu tải model, không gọi OpenAI):

```bash
python -m scripts.smoke_embedding
```

## Đóng gói Python

```bash
pip wheel . --no-deps --no-build-isolation -w dist
pip install dist/legal_rag_project-1.1.0-py3-none-any.whl
uvicorn backend.api:app --host 127.0.0.1 --port 8000 --workers 1
```

Wheel chứa backend, frontend và client CLI, không chứa tài liệu, database, key hoặc trọng số model. `LLM_MODEL` tùy chỉnh phải hỗ trợ Chat Completions Structured Outputs và `temperature=0`.

Kết quả kiểm chứng của bản bàn giao: xem [VERIFICATION.md](VERIFICATION.md). Các số liệu trong đó là kiểm thử chức năng bằng PDF tự tạo; chưa phải benchmark độ đúng pháp lý.
