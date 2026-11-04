from dotenv import load_dotenv
from src.embedding import LegalEmbedding
from src.vector_store import get_or_create_collection

load_dotenv('./.env')

test_questions = [
    "Điều kiện để được cấp giấy phép thành lập tổ chức tín dụng là gì?",
    "Ngân hàng Nhà nước đặt tổ chức tín dụng vào kiểm soát đặc biệt khi nào?",
    "Thành viên Hội đồng quản trị của ngân hàng thương mại phải đáp ứng điều kiện gì?",
    "Tổng mức dư nợ cấp tín dụng tối đa cho một khách hàng là bao nhiêu phần trăm?",
]

embedder = LegalEmbedding()
collection = get_or_create_collection('./db', 'legal_database')


def retrieve(question, n_results=3, threshold=0.5):
    query_vector = embedder.embed([question])
    ans = collection.query(
        query_embeddings=query_vector,
        n_results=n_results,
        include=["documents", "distances"]
    )
    documents = ans["documents"][0]
    distances = ans["distances"][0]
    return [(documents[i], distances[i]) for i in range(len(documents)) if distances[i] < threshold]


for i, question in enumerate(test_questions):
    print(f"[{i+1}] {question}")
    results = retrieve(question)
    if not results:
        print("  Không tìm thấy doc nào (vượt threshold 0.5)")
    else:
        for j, (doc, dist) in enumerate(results):
            print(f"\n  [Context {j+1}] distance={dist:.4f}")
            print(f"  {doc[:300]}...")
