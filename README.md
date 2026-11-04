# Legal RAG Workspace

Ứng dụng tra cứu tài liệu tiếng Việt với giao diện web và backend FastAPI. Upload PDF, theo dõi xử lý, tìm đoạn gốc, hỏi đáp có căn cứ và mở đúng trang nguồn trong cùng một giao diện.

## Chạy ứng dụng

Từ thư mục gốc project, dùng Python 3.12 (đã kiểm thử):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env
python app.py
```

- **Giao diện:** <http://127.0.0.1:8000/>
- **Swagger/API:** <http://127.0.0.1:8000/docs>
- Có thể thay `python app.py` bằng `uvicorn backend.api:app --host 127.0.0.1 --port 8000 --workers 1`.
- Không cần Node, npm build hoặc Streamlit để chạy giao diện. Frontend HTML/CSS/JavaScript được FastAPI phục vụ cùng origin.
- **Rerank:** kết quả tìm kiếm được chấm lại bằng cross-encoder `RERANKER_MODEL` (mặc định `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, ~470MB, tải lần đầu về `HF_HOME`). Để trống biến này để tắt. Câu hỏi không dấu bỏ qua bước rerank. Nếu model không tải được, tìm kiếm vẫn chạy không rerank.
- Chỉ chạy một process trên mỗi `DATA_DIR`. Dữ liệu nằm trong `data/backend`; model cache theo `HF_HOME` trong `.env`.

## Dùng giao diện

1. Mở **Kho tài liệu**, chọn hoặc kéo thả một hay nhiều PDF. Trạng thái tự cập nhật.
2. Khi file **Đã xử lý**, mở **Hồ sơ và duyệt nguồn**: nhập mã, tên, phiên bản, URL nguồn, căn cứ nguồn và ghi chú hiệu lực. Ngày chưa xác định để trống.
3. Đối chiếu các đoạn với PDF, ghi người duyệt và quyết định **Duyệt nguồn**. Chỉ bản đã duyệt mới tham gia tra cứu.
4. Mở **Tra cứu**, chọn phạm vi tài liệu và nhập câu hỏi.
5. **Tìm đoạn gốc** truy xuất nội dung trực tiếp, không cần OpenAI API key.
6. **Hỏi đáp AI** được bật khi backend đã cấu hình `OPENAI_API_KEY` trong `.env` và được khởi động lại.
7. Mở nguồn để đọc trang gốc; dùng nút trước/sau để chuyển trang hoặc tải toàn bộ PDF.

Nếu backend có `BACKEND_API_KEY`, nhập key trong **Cài đặt kết nối** trên giao diện. Key chỉ được giữ trong bộ nhớ của trang, không lưu localStorage và không đưa vào URL. Đây là key truy cập backend, không phải OpenAI API key.

Trong hồ sơ có **Nạp phiên bản mới**, quan hệ **sửa đổi/thay thế** và lịch sử chỉnh sửa. Sửa hồ sơ/quan hệ sẽ rút duyệt, yêu cầu duyệt lại. File mới không ghi đè bản cũ. Chi tiết: [quy trình P0](docs/P0.md).

Hỏi đáp AI hiện chọn các trích đoạn nguyên văn được backend kiểm tra với nguồn; không hiển thị lời diễn giải tự do của model.

PDF scan cần OCR trước. Tài liệu tải lên chưa được xác minh hiệu lực pháp lý. Mỗi câu hỏi xử lý độc lập; lịch sử tra cứu chỉ ở trong trang hiện tại và mất khi tải lại trang.

## Cấu trúc thư mục

```text
legal_rag_project-/
├── backend/                 # FastAPI, nghiệp vụ và lưu trữ
│   ├── api.py               # HTTP routes + phục vụ frontend
│   ├── legal.py             # Schema hồ sơ, ngày và duyệt nguồn
│   ├── config.py            # Cấu hình từ .env
│   ├── service.py           # Upload, ingestion, tìm kiếm và hỏi đáp
│   ├── documents.py         # SQLite registry và hàng đợi
│   ├── parsing.py           # Trích xuất PDF, giữ trang và Điều
│   ├── vectors.py           # Embedding và ChromaDB
│   └── generation.py        # OpenAI Structured Outputs
├── frontend/                # Giao diện web, đóng gói cùng backend
│   ├── index.html           # Hai màn hình Tra cứu / Kho tài liệu
│   └── assets/
│       ├── styles.css       # Design system và responsive layout
│       ├── app.js           # State, tương tác và render giao diện
│       ├── legal.js         # Hồ sơ, phiên bản, duyệt và lịch sử
│       └── api.js           # HTTP client và xử lý lỗi
├── clients/cli.py           # Client dòng lệnh
├── scripts/                 # Tải model và smoke test
├── tests/                   # Python integration tests + JavaScript client tests
├── docs/                    # Tài liệu API, kiểm chứng và cấu trúc
├── experiments/             # Pipeline, notebook và Streamlit cũ, tách khỏi sản phẩm
├── data/                    # File, DB và model cache (không đưa vào Git)
├── app.py                   # Entry point chạy web + API
├── main.py                  # Entry point tương thích cho CLI
├── Dockerfile
├── compose.yaml
├── pyproject.toml
└── .env.example
```

Chi tiết ranh giới module và quy ước phát triển: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Công cụ khác

```bash
# CLI, cần backend đang chạy
python -m clients.cli
# python main.py vẫn được hỗ trợ.

# Tải sẵn model; giữ file dở nếu mạng bị gián đoạn
python -m scripts.prefetch_model

# Smoke test model thật, không gọi OpenAI
python -m scripts.smoke_embedding

# Docker, giao diện và API cùng cổng 8000
# Điền .env theo nhu cầu trước khi chạy.
docker compose up --build -d
```

## Kiểm thử và đóng gói

```bash
pip install -r requirements-dev.txt
pytest -q

# Test JavaScript client, nếu có Node.js 20+
node --test tests/frontend.test.mjs

# Wheel chứa cả backend, frontend và CLI
pip wheel . --no-deps --no-build-isolation -w dist
```

Không cần dependency npm cho test JavaScript. Các thư mục `experiments/`, `data/`, `.env`, test và ảnh kiểm chứng không được đưa vào wheel/Docker image. Không build đè nội dung frontend bằng dữ liệu giả lập.

- [API và vận hành](docs/API.md)
- [Kết quả kiểm chứng](docs/VERIFICATION.md)
- [Code thử nghiệm được lưu lại](experiments/README.md)
