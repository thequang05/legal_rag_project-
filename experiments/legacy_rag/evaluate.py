from dotenv import load_dotenv
import os
import time
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, LLMContextPrecisionWithoutReference
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import HuggingFaceEmbeddings
from src.embedding import LegalEmbedding
from src.rag_pipeline import LegalRAGPipeline
from src.vector_store import get_or_create_collection

load_dotenv('./.env')
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

test_questions = [
    "Điều kiện để được cấp giấy phép thành lập tổ chức tín dụng là gì?",
    "Ngân hàng Nhà nước đặt tổ chức tín dụng vào kiểm soát đặc biệt khi nào?",
    "Thành viên Hội đồng quản trị của ngân hàng thương mại phải đáp ứng điều kiện gì?",
    "Tổng mức dư nợ cấp tín dụng tối đa cho một khách hàng là bao nhiêu phần trăm?",
    "Ngân hàng Nhà nước thu hồi giấy phép của tổ chức tín dụng trong trường hợp nào?",
    "Những hành vi nào bị nghiêm cấm trong hoạt động ngân hàng?",
    "Cá nhân được sở hữu tối đa bao nhiêu phần trăm cổ phần của một ngân hàng thương mại?",
    "Tổ chức tín dụng có nghĩa vụ bảo mật thông tin khách hàng như thế nào?",
    "Hệ thống kiểm soát nội bộ của tổ chức tín dụng là gì và nhằm mục đích phòng ngừa rủi ro như thế nào?",
    "Tổ chức tín dụng được quyền ấn định lãi suất như thế nào?",
]

embedder = LegalEmbedding()
collection = get_or_create_collection('./db', 'legal_database')
rag = LegalRAGPipeline(collection, embedder, OPENAI_API_KEY)

questions, answers, contexts = [], [], []

for question in test_questions:
    retrieved_docs = rag.retrieve(question)
    answer = rag.generate_answer(question, "\n\n".join(retrieved_docs))
    questions.append(question)
    answers.append(answer)
    contexts.append(retrieved_docs)
    time.sleep(5)

data = {
    "question": questions,
    "answer": answers,
    "contexts": contexts,
}
dataset = Dataset.from_dict(data)

ragas_llm = LangchainLLMWrapper(ChatOpenAI(model="gpt-4o", api_key=OPENAI_API_KEY, temperature=0))
ragas_embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(model_name="paraphrase-multilingual-MiniLM-L12-v2"))

result = evaluate(
    dataset=dataset,
    metrics=[faithfulness, answer_relevancy, LLMContextPrecisionWithoutReference()],
    llm=ragas_llm,
    embeddings=ragas_embeddings,
)

df = result.to_pandas()
print(df[["user_input", "faithfulness", "answer_relevancy", "llm_context_precision_without_reference"]])
print("\n Điểm trung bình ")
print(df[["faithfulness", "answer_relevancy", "llm_context_precision_without_reference"]].mean().round(4))
