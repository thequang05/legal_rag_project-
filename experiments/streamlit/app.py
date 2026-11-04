"""Optional Streamlit client. All ingestion and RAG run in the backend API."""
import os

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
BASE = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
HEADERS = {"X-API-Key": os.getenv("BACKEND_API_KEY", "")}
st.title("Legal RAG — Tra cứu tài liệu")
st.caption("Tài liệu tải lên chưa được xác minh hiệu lực pháp lý.")


def api(method, path, **kwargs):
    try:
        response = httpx.request(method, BASE + path, headers=HEADERS, timeout=180, **kwargs)
        response.raise_for_status()
        return response
    except httpx.HTTPStatusError as exc:
        st.error(f"API {exc.response.status_code}: {exc.response.text}")
    except httpx.RequestError:
        st.error("Không kết nối được backend. Hãy chạy uvicorn backend.api:app trước.")
    return None


with st.sidebar:
    st.header("Tài liệu")
    file = st.file_uploader("Chọn PDF", type=["pdf"])
    if st.button("Upload và xử lý", disabled=file is None):
        response = api("POST", "/documents", files={"file": (file.name, file.getvalue(), "application/pdf")})
        if response is not None:
            st.success("Tài liệu đã tồn tại." if response.json()["duplicate"] else "Đã nhận file; đang xử lý nền.")
    st.button("Làm mới trạng thái")
    response = api("GET", "/documents")
    docs = response.json() if response is not None else []
    for doc in docs:
        st.write(f"{doc['filename']} — {doc['status']}")
        if doc["error"]:
            st.caption(doc["error"])
        if doc["status"] == "failed" and st.button("Thử lại", key="retry" + doc["id"]):
            api("POST", f"/documents/{doc['id']}/retry")
            st.rerun()
        if st.button("Xóa", key="delete" + doc["id"]):
            api("DELETE", f"/documents/{doc['id']}")
            st.rerun()
    ready = {doc["id"]: doc["filename"] for doc in docs if doc["status"] == "ready"}
    selected = st.multiselect("Giới hạn nguồn (để trống: tất cả)", list(ready), format_func=ready.get)

if "messages" not in st.session_state:
    st.session_state.messages = []
def render_message(message, position):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        for source in message.get("citations", []):
            with st.expander(f"[{source['citation_id']}] {source['filename']} — trang {source['page']} {source['article']}"):
                st.text(source["text"])
                if st.button("Lấy PDF nguồn", key=f"fetch-{position}-{source['chunk_id']}"):
                    original = api("GET", f"/documents/{source['document_id']}/file")
                    if original is not None:
                        st.download_button("Tải PDF nguồn", original.content, file_name=source["filename"],
                                           mime="application/pdf", key=f"download-{position}-{source['chunk_id']}")


for position, message in enumerate(st.session_state.messages):
    render_message(message, position)

question = st.chat_input("Nhập câu hỏi...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.spinner("Đang tra cứu..."):
        response = api("POST", "/ask", json={"question": question, "document_ids": selected})
    if response is not None:
        result = response.json()
        st.session_state.messages.append({"role": "assistant", "content": result["answer"], "citations": result["citations"]})
        st.rerun()
