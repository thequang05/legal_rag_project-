from threading import Lock
import hashlib


class VectorIndex:
    def __init__(self, path, model_name):
        self.path = path
        self.model_name = model_name
        self._collection = None
        self._embedder = None
        self._lock = Lock()

    @property
    def collection(self):
        if self._collection is None:
            import chromadb
            from chromadb.config import Settings
            client = chromadb.PersistentClient(path=str(self.path), settings=Settings(anonymized_telemetry=False))
            # Separate collections prevent mixing embeddings from different model configurations.
            suffix = hashlib.sha256(self.model_name.encode()).hexdigest()[:12]
            self._collection = client.get_or_create_collection(
                name=f"legal_api_{suffix}", embedding_function=None,
                configuration={"hnsw": {"space": "cosine"}})
        return self._collection

    def _load_embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(self.model_name)
        return self._embedder

    def prepare_chunks(self, chunks):
        # Character limits alone do not prevent the embedding model truncating Vietnamese.
        with self._lock:
            model = self._load_embedder()
            tokenizer = model.tokenizer
            budget = model.max_seq_length - tokenizer.num_special_tokens_to_add(pair=False) - 8
            if budget < 16:
                raise ValueError("Embedding model has an unsupported sequence limit.")
            prepared = []
            for chunk in chunks:
                offsets = tokenizer(chunk["text"], add_special_tokens=False,
                                    truncation=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
                offsets = [(a, b) for a, b in offsets if b > a]
                if len(offsets) <= budget:
                    prepared.append(chunk)
                    continue
                position = 0
                while position < len(offsets):
                    end = min(position + budget, len(offsets))
                    text = chunk["text"][offsets[position][0]:offsets[end - 1][1]].strip()
                    if text:
                        left = offsets[position][0]
                        right = offsets[end - 1][1]
                        raw = chunk["text"][left:right]
                        left += len(raw) - len(raw.lstrip())
                        right -= len(raw) - len(raw.rstrip())
                        prepared.append({**chunk, "text": text,
                            "start_char": chunk.get("start_char", 0) + left,
                            "end_char": chunk.get("start_char", 0) + right})
                    if end == len(offsets):
                        break
                    position = end - min(16, budget // 4)
            return prepared

    def embed(self, texts):
        with self._lock:
            model = self._load_embedder()
            tokens = model.tokenizer(texts, truncation=False, add_special_tokens=True)["input_ids"]
            if any(len(ids) > model.max_seq_length for ids in tokens):
                raise ValueError("Chunk vượt giới hạn token của model; không tạo embedding bị cắt nội dung.")
            return model.encode(texts, normalize_embeddings=True).tolist()

    def embed_query(self, question):
        chunks = self.prepare_chunks([{"text": question, "page": 0, "article": ""}])
        vectors = self.embed([chunk["text"] for chunk in chunks])
        pooled = [sum(values) / len(vectors) for values in zip(*vectors)]
        norm = sum(value * value for value in pooled) ** 0.5
        if not norm:
            raise ValueError("Không thể tạo vector cho câu hỏi.")
        return [value / norm for value in pooled]

    def with_context(self, context, text):
        """Prefix text with its legal context for embedding, trimmed to the model's token limit."""
        if not context:
            return text
        with self._lock:
            model = self._load_embedder()
            tokenizer = model.tokenizer
            limit = model.max_seq_length

            def fits(candidate):
                return len(tokenizer(candidate, truncation=False, add_special_tokens=True)["input_ids"]) <= limit
            words = context.split()
            while words:
                candidate = f"{' '.join(words)}\n{text}"
                if fits(candidate):
                    return candidate
                words.pop()
        return text

    def add(self, document_id, filename, chunks, contexts=None):
        contexts = contexts or [""] * len(chunks)
        for start in range(0, len(chunks), 32):
            batch = chunks[start:start + 32]
            texts = [chunk["text"] for chunk in batch]
            embed_texts = [self.with_context(ctx, text) for ctx, text in zip(contexts[start:start + 32], texts)]
            self.collection.upsert(
                ids=[f"{document_id}:{start+i}" for i in range(len(batch))],
                documents=texts, embeddings=self.embed(embed_texts),
                metadatas=[{"document_id": document_id, "filename": filename,
                            "page": chunk["page"], "article": chunk["article"]} for chunk in batch])

    def delete(self, document_id):
        self.collection.delete(where={"document_id": document_id})

    def distances(self, question, chunk_ids):
        """Cosine distance from the question to specific stored chunks."""
        if not chunk_ids:
            return {}
        query = self.embed_query(question)
        stored = self.collection.get(ids=list(chunk_ids), include=["embeddings"])
        result = {}
        for chunk_id, vector in zip(stored["ids"], stored["embeddings"]):
            result[chunk_id] = 1.0 - sum(a * b for a, b in zip(query, vector))
        return result

    def search(self, question, document_ids, top_k):
        if not document_ids:
            return []
        result = self.collection.query(
            query_embeddings=[self.embed_query(question)], n_results=top_k,
            where={"document_id": {"$in": document_ids}},
            include=["documents", "metadatas", "distances"])
        return [{"chunk_id": chunk_id, "text": text, "distance": distance, **metadata}
                for chunk_id, text, metadata, distance in zip(
                    result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0])]
