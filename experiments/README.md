# Code thử nghiệm được lưu lại

- `legacy_rag/`: pipeline ban đầu, notebook, prompt và script đánh giá. Đây là bản lưu lịch sử; đường dẫn PDF/DB vẫn thuộc thiết kế cũ. Không chạy các script này để đánh giá kho dữ liệu backend mới.
- `streamlit/`: giao diện Streamlit cũ gọi HTTP API. Giao diện chính hiện ở `frontend/`, mở tại `/` của FastAPI và không cần Streamlit.

Các thư mục này không được đưa vào wheel hoặc Docker image sản phẩm. Dependency tùy chọn nằm trong `requirements.txt` của từng thư mục, cùng thư mục `src` và `configs` cũ trong `legacy_rag`.
