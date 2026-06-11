from openai import OpenAI
from configs.prompts import LEGAL_QA_PROMPT


class LegalRAGPipeline:
    def __init__(self, vector_db_collection, embedding_model, api_key):
        self.collection = vector_db_collection
        self.client = OpenAI(api_key=api_key)
        self.model_name = 'gpt-4o-mini'
        self.embedding_model = embedding_model

    def retrieve(self, question, n_results=3, threshold=0.5):
        query_vector = self.embedding_model.embed([question])
        ans = self.collection.query(query_embeddings=query_vector, n_results=n_results, include=["documents", "distances"])
        documents = ans["documents"][0]
        distances = ans["distances"][0]
        return [documents[i] for i in range(len(documents)) if distances[i] < threshold]

    def generate_answer(self, question, context):
        prompt = LEGAL_QA_PROMPT.format(context=context, question=question)
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content

    def ask(self, question):
        print(f"Đang tìm kiếm tài liệu cho câu hỏi: '{question}'...")
        relevant_docs = self.retrieve(question)
        if not relevant_docs:
            return "Không tìm thấy thông tin liên quan trong cơ sở dữ liệu pháp lý."
        print("Đang tổng hợp câu trả lời...")
        answer = self.generate_answer(question, "\n\n".join(relevant_docs))
        return answer