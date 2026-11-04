from sentence_transformers import SentenceTransformer
class LegalEmbedding:
    def __init__(self,model_name='paraphrase-multilingual-MiniLM-L12-v2'):
        self.model=SentenceTransformer(model_name)
    def embed(self,texts):
        if not texts:
            raise ValueError("Vui lòng truyền vào 1 mảng khác rỗng")
        return self.model.encode(texts).tolist()
