from dotenv import load_dotenv
import os
from src.embedding import LegalEmbedding
from src.rag_pipeline import LegalRAGPipeline
from src.data_loader import load_and_clean_pdf
from src.text_splitter import split_by_article
from src.vector_store import get_or_create_collection, add_documents


def main():
    load_dotenv('./.env')
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    data_path = './data/raw/158-vbhn-vpqh.pdf'

    embedder = LegalEmbedding()
    collection = get_or_create_collection('./db', 'legal_database')

    if collection.count() == 0:
        text = load_and_clean_pdf(data_path)
        chunks = split_by_article(text)
        embeddings = embedder.embed(chunks)
        add_documents(collection, chunks, embeddings)

    rag = LegalRAGPipeline(collection, embedder, OPENAI_API_KEY)

    question = input('Vui long nhap cau hoi, nhap so 1 de thoat: ')
    while question != '1':
        answer = rag.ask(question)
        print(answer)
        question = input('Vui long nhap cau hoi, nhap so 1 de thoat: ')


if __name__ == '__main__':
    main()

