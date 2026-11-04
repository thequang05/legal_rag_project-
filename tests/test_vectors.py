from backend.vectors import VectorIndex


class CharacterTokenizer:
    def num_special_tokens_to_add(self, pair=False):
        return 2

    def __call__(self, text, **kwargs):
        return {"offset_mapping": [(i, i + 1) for i in range(len(text))]}


class SmallModel:
    tokenizer = CharacterTokenizer()
    max_seq_length = 64


def test_embedding_chunks_preserve_content_and_metadata_within_token_limit(tmp_path):
    index = VectorIndex(tmp_path, "test")
    index._embedder = SmallModel()
    text = "".join(chr(0x400 + i) for i in range(260))
    chunks = index.prepare_chunks([{"text": text, "page": 3, "article": "Điều 2", "start_char":27, "end_char":287, "clause":"2", "point":"a"}])
    assert len(chunks) > 1
    assert all(len(c["text"]) + 2 <= 64 for c in chunks)
    assert all(c["page"] == 3 and c["article"] == "Điều 2" for c in chunks)
    assert all(text[c["start_char"]-27:c["end_char"]-27] == c["text"] for c in chunks)
    assert all(c["clause"]=="2" and c["point"]=="a" for c in chunks)
    assert chunks[0]["text"].startswith(text[:20])
    assert text.endswith(chunks[-1]["text"])
    assert all(text[i:i + 8] in "|".join(c["text"] for c in chunks) for i in range(len(text) - 7))


def test_long_question_is_embedded_in_full_without_truncation(tmp_path):
    class Array:
        def __init__(self, data):
            self.data = data
        def tolist(self):
            return self.data

    class QueryModel(SmallModel):
        def __init__(self):
            self.seen = []
        def encode(self, texts, **kwargs):
            self.seen.extend(texts)
            return Array([[1.0, float(len(text))] for text in texts])

    class Tokenizer(CharacterTokenizer):
        def __call__(self, texts, **kwargs):
            if isinstance(texts, list):
                return {"input_ids": [list(range(len(text) + 2)) for text in texts]}
            return super().__call__(texts, **kwargs)

    index = VectorIndex(tmp_path, "test")
    model = QueryModel()
    model.tokenizer = Tokenizer()
    index._embedder = model
    question = "".join(chr(0x400 + i) for i in range(260))
    vector = index.embed_query(question)
    assert len(model.seen) > 1
    assert all(len(text) + 2 <= model.max_seq_length for text in model.seen)
    assert all(question[i:i + 8] in "|".join(model.seen) for i in range(len(question) - 7))
    assert abs(sum(value * value for value in vector) - 1) < 1e-6
