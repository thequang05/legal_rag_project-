# Cấu trúc và ranh giới trách nhiệm

## Luồng runtime

```text
Trình duyệt / CLI
       │ HTTP, cùng origin với frontend
       ▼
backend/api.py
       ▼
backend/service.py
  ├── documents.py → SQLite: metadata, trạng thái và hàng đợi
  ├── parsing.py   → text/chunk theo trang
  ├── vectors.py   → embedding và ChromaDB
  └── generation.py → câu trả lời có cấu trúc và citation
```

- `frontend/index.html` định nghĩa giao diện và accessibility labels. `styles.css` quản lý màu, typography và breakpoint. `legal.js` quản lý hồ sơ, phiên bản, duyệt và lịch sử. `app.js` quản lý state, tương tác, polling và render. `api.js` tập trung request, auth header, timeout và xử lý lỗi.
- Frontend chỉ gọi HTTP; không đọc SQLite, đường dẫn file hoặc API key của nhà cung cấp AI. Kết quả, tên tài liệu và đoạn trích luôn được gán qua text node để không thực thi HTML từ tài liệu/LLM.
- HTML và asset công khai, nhưng mọi endpoint dữ liệu, capability và ảnh trang PDF vẫn áp dụng `BACKEND_API_KEY` nếu được cấu hình.
- Mỗi trang PDF được backend render thành PNG với cạnh tối đa khoảng 2048 pixel. Trình xem không phụ thuộc plugin PDF của trình duyệt; PDF gốc vẫn tải được. URL ảnh/PDF tạm được thu hồi khi đóng hộp xem.
- Khi đổi phần nghiệp vụ, sửa `backend/` và test Python. Khi đổi trải nghiệm, sửa `frontend/`; dùng test JS cho HTTP client và kiểm tra trực tiếp trên trình duyệt.
- `app.py` và `main.py` chỉ là entry point mỏng. Code CLI thực tế nằm ở `clients/cli.py`.
- `scripts/` là công cụ vận hành/kiểm chứng, không phải service runtime. `docs/` chứa tài liệu; dữ liệu local luôn nằm dưới `DATA_DIR`/`HF_HOME`, mặc định trong `data/`.
- `experiments/` giữ nguyên các ý tưởng/thí nghiệm ban đầu để tham khảo, không được import vào code sản phẩm hoặc đóng gói vào wheel/Docker.

## Sau khi thay đổi

1. Chạy test phù hợp với thay đổi; kiểm tra lại trình duyệt sau khi sửa UI.
2. Model embedding thay đổi cần kho mới. Chunk schema 2 → 3 tự nạp lại từ PDF, giữ ID và metadata; các bản cũ mặc định chờ duyệt. Không di chuyển `data/backend`.
3. Build wheel từ cây source sạch. Xác nhận wheel có `frontend/index.html` và asset để cài ngoài repo vẫn chạy được.
4. Cập nhật README, tài liệu API và kiểm chứng khi đổi đường dẫn/cách chạy.

## Phần chưa có

Chưa có OCR, xác minh hiệu lực văn bản, hội thoại nhiều lượt theo ngữ cảnh, SSO/quyền từng tài liệu hoặc worker phân tán. Shared API key áp dụng toàn kho. Câu trả lời dùng quote nguyên văn đã kiểm tra; việc chọn đoạn không tự chứng minh đã bao quát đủ điều kiện, ngoại lệ hay hiệu lực pháp lý.

Registry lưu metadata theo phiên bản, revision để chống ghi đè chỉnh sửa và snapshot lịch sử. Chunks nguyên văn cùng offsets nằm trong SQLite; Chroma chỉ dùng tìm ứng viên. Search đối chiếu lại nội dung chunk, chỉ cho bản `ready` + `approved`. `/ask` bỏ lời diễn giải của model, chỉ dựng câu trả lời từ quote khớp chính xác; kiểm tra lại revision/duyệt sau khi model trả về. Xem [P0.md](P0.md).
