from dataclasses import dataclass
from pathlib import Path
import os


DEFAULT_RERANKER = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    api_key: str = ""
    openai_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    reranker_model: str = ""
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pages: int = 500
    max_chunks: int = 10000

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        load_dotenv()
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "./data/backend")).resolve(),
            api_key=os.getenv("BACKEND_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            embedding_model=os.getenv("EMBEDDING_MODEL", cls.embedding_model),
            reranker_model=os.getenv("RERANKER_MODEL", DEFAULT_RERANKER),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(cls.max_upload_bytes))),
            max_pages=int(os.getenv("MAX_PDF_PAGES", "500")),
        )
