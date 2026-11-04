"""CLI client for the backend; upload documents using /docs first."""
import os
import httpx
from dotenv import load_dotenv


def main():
    load_dotenv()
    base = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
    with httpx.Client(base_url=base, headers={"X-API-Key": os.getenv("BACKEND_API_KEY", "")}, timeout=180) as client:
        while True:
            question = input("Nhập câu hỏi (1 để thoát): ").strip()
            if question == "1":
                return
            if not question:
                continue
            try:
                response = client.post("/ask", json={"question": question})
                response.raise_for_status()
                result = response.json()
                print(result["answer"])
                for source in result["citations"]:
                    print(f"[{source['citation_id']}] {source['filename']} — trang {source['page']}: {base}{source['source_url']}")
            except httpx.HTTPError as exc:
                print(f"Lỗi API: {exc}")


if __name__ == "__main__":
    main()
