import chromadb
from google import genai
from dotenv import load_dotenv
import os
from src.embedding import LegalEmbedding
from src.rag_pipeline import LegalRAGPipeline
from src.data_loader import load_and_clean_pdf
from src.text_splitter import split_by_article
from src.vector_store import get_or_create_collection,add_documents
def main():
    load_dotenv('./.env')
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    data_path='./data/raw/158-vbhn-vpqh.pdf'
    text=load_and_clean_pdf(data_path)
    chunks=split_by_article(text)
    embedder=LegalEmbedding()
    embeddings=embedder.embed(chunks)
    collection=get_or_create_collection('./db','legal_database')
    add_documents(collection,chunks,embeddings)
    question=input('Vui long nhap cau hoi, nhap so 1 de thoat')
    rag=LegalRAGPipeline(collection,embedder,GEMINI_API_KEY)
    while question != '1':
        answer=rag.ask(question)
        print(answer)
        question=input('Vui long nhap cau hoi, nhap so 1 de thoat')
if __name__ == '__main__':
    main()

