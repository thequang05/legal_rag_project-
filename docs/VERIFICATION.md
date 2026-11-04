# Kiểm chứng giao diện và backend API

## Bản 1.1 P0 — 2026-10-17

- **33 test Python + 8 test JavaScript đạt**. Đây là kiểm thử chức năng/invariant; không xây dựng bộ đánh giá chuẩn theo yêu cầu.
- `tests/test_p0.py`: metadata, ngày, revision conflict, PATCH từng trường không làm mất dữ liệu, cổng duyệt, phiên bản/dedup, xóa đúng bản, phục hồi cùng ID về draft, quan hệ và chặn vòng lặp, auth các route P0.
- Parser/nguồn: PDF tiếng Việt hai trang có Điều/Khoản/Điểm, tiếp nối khoản qua trang; đối chiếu exact offsets với PDF thật; ảnh đánh dấu khác ảnh gốc; chặn chunk khác tài liệu/trang. Token splitting giữ offsets đã được kiểm tra.
- Claims: quote phải nằm nguyên văn trong nguồn, ID đúng, không rỗng; bỏ lời diễn giải ngoài schema. Rút duyệt trong lúc sinh đáp án làm hệ thống bỏ kết quả. OpenAI SDK được kiểm tra qua HTTP mock; chưa gọi provider bằng key thật.
- Migration: dựng registry kiểu cũ và chunk schema 2, nâng sang 3 giữ nguyên bytes PDF và ID, tái xử lý có đoạn nguồn, mặc định draft.
- Model thật: smoke PDF tiếng Việt với Chroma persistent và model cached, chạy offline. Kiểm tra upload → metadata → duyệt → search → exact offsets → xóa. 6 chunk, câu hỏi ngắn có distance khoảng 0.2255.
- Wheel 1.1.0: cài vào thư mục tách biệt, chạy ngoài repo; xác nhận import backend từ wheel, frontend/asset legal.js, các route P0. Chạy lại smoke model thật từ backend trong wheel thành công.
- GUI: đã thử lưu metadata, duyệt bản 1, nạp bản 2 cùng nhóm về draft, ghi quan hệ thay thế bản 1; tra cứu chỉ bản 1 đã duyệt; mở PDF đánh dấu Điều 1/Khoản 1 cùng quote, ID, SHA-256 và revision. Bộ lọc duyệt nguồn đã kiểm tra trực tiếp.
- Responsive hồ sơ: 375 px, pageWidth=375 và dialogWidth=343, nội dung dialog không tràn ngang. Reset viewport sau kiểm tra.
- PDF giả dùng cho GUI được dọn khỏi kho hoạt động; tombstone/lịch sử vẫn được giữ theo thiết kế. Không sửa/xóa tài liệu khác.
- `pip check`, `git diff --check`, `docker compose config --quiet` đạt. Chưa build/chạy Docker image.
- Ảnh bằng chứng: [Hồ sơ và duyệt](screenshots/p0-document-review.png), [nguồn trích dẫn](screenshots/p0-source-evidence-final.png).

## Lịch sử bản đầu — 2026-10-15

Môi trường kiểm thử: macOS ARM64, Python 3.12.14. FastAPI 0.143.1, ChromaDB 1.5.9, Sentence Transformers 5.7.0, OpenAI SDK 2.54.0.

| Hạng mục | Bằng chứng / kết quả |
|---|---|
| Bộ test tự động | `python -m pytest -q`: **24 passed**. PDF và Chroma persistent thật; embedding/generator xác định cho test offline. |
| Upload, nhiều tài liệu, chống trùng | Upload → ready; namespace chunk theo SHA-256; cùng bytes trả bản đã có; filter nguồn và xóa không ảnh hưởng tài liệu khác. |
| Xử lý lỗi / restart | PDF lỗi/scan/mật khẩu/quá giới hạn, partial index, retry, khôi phục processing/deleting, file lock và đổi model có test. |
| Embedding token limit | Kiểm tra chunk và câu hỏi dài không bị âm thầm truncate; giữ nguồn trang. |
| Câu trả lời / citation | Test API với generator giả lập và OpenAI SDK qua HTTP mock; citation ID sai bị từ chối, thiếu API key trả 503 khi cần sinh đáp án. |
| HTTP thật | Uvicorn localhost: `/health`, `/docs`, `/openapi.json`, `/documents` trả 200; `/ask` khi kho rỗng trả chưa đủ thông tin. Server bàn giao chạy tại `127.0.0.1:8000`, giao diện ở `/`. |
| Gói Python | Wheel build thành công, archive hợp lệ, cài vào thư mục tách biệt và xác nhận import backend từ chính gói đó. |
| Embedding thật từ wheel | Chạy script smoke ở ngoài repo, dùng backend đã cài từ wheel, `HF_HUB_OFFLINE=1`. Model `paraphrase-multilingual-MiniLM-L12-v2` thật và Chroma thật. |
| PDF tiếng Việt tự tạo | Upload tạo **6 chunk**, nhận đúng **Điều 1**, nguồn trang 1; câu hỏi ngắn có kết quả với cosine distance khoảng **0.2255**, dưới ngưỡng mặc định 0.5. Câu hỏi dài được xử lý, trả 5 nguồn khi đặt max_distance=2 để kiểm tra đường đi dữ liệu; xóa xong tìm kiếm trả rỗng. |
| Tải model không ổn định | Lần tải đầu timeout/DNS và thất bại. Công cụ `scripts.prefetch_model` sau đó hoàn tất tải có tiếp tục file dở, xác minh SHA-256; cache model hiện có tại `data/model-cache` (không đưa vào Git/wheel). |
| Dependency / source | `pip check`: không có dependency hỏng. `git diff --check`: không có lỗi whitespace. |
| Docker | `docker compose config --quiet` đạt. Chưa build/chạy image vì Docker daemon chưa chạy. |

## Frontend và cấu trúc thư mục

- `node --test tests/frontend.test.mjs`: **6 passed**. Bao phủ phân trang, auth header, upload multipart, phạm vi truy vấn, lỗi HTTP/network, PDF/PNG và tìm tên tiếng Việt.
- Kiểm tra trực tiếp trong trình duyệt: chọn nhiều file (PDF hợp lệ và file giả PDF), upload → processing → ready, lọc tên, chọn phạm vi, hỏi tìm đoạn gốc tiếng Việt và mở trang nguồn. PDF tự tạo cho UI có 1 trang, tạo 3 chunk; đã xóa đúng tài liệu thử sau khi kiểm tra.
- Trình xem dùng ảnh PNG render từ PDF, đã nhìn thấy nội dung trang; không phụ thuộc plugin PDF. Đã kiểm tra hộp cài đặt và mở/hủy xác nhận xóa. Retry lỗi được kiểm tra qua API; chưa thực hiện toàn bộ thao tác retry bằng GUI.
- Responsive: đã nhìn giao diện trên desktop và màn hình 375 px; sửa lỗi phần tử accessibility của bảng làm trang tràn ngang. Bảng tài liệu cuộn trong vùng riêng.
- Wheel mới chứa `backend`, `frontend/index.html`, CSS/JS và `clients`; không chứa experiments, dữ liệu hay `.env`. Cài wheel vào `/private/tmp/legal-rag-wheel-check`, chạy ngoài repo và xác nhận `/`, asset, `/capabilities`, `/docs` trả 200.
- Source sản phẩm nằm trong `backend/`, `frontend/`, `clients/`; pipeline/notebook/Streamlit cũ được chuyển vào `experiments/`. Không di chuyển kho dữ liệu runtime.
- Ảnh giao diện đã kiểm tra: [frontend-desktop.png](screenshots/frontend-desktop.png).

## Giới hạn của kết quả

- Chưa gọi OpenAI bằng API key thật; kiểm thử không phát sinh phí LLM.
- PDF thử là nội dung tự tạo để kiểm tra chức năng, không phải văn bản luật được xác minh. Chưa đánh giá độ đúng pháp lý, hiệu lực văn bản hoặc chất lượng trả lời trên benchmark chuẩn.
- Có cảnh báo deprecation từ kiểu SWIG của PyMuPDF; các test vẫn đạt.
- Phiên bản này dùng shared API key và một process trên mỗi DATA_DIR. Chưa có OCR, SSO, phân quyền từng tài liệu, nhiều tenant hoặc hạ tầng scale-out.
