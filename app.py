import streamlit as st
from dotenv import load_dotenv
import os
from src.embedding import LegalEmbedding
from src.rag_pipeline import LegalRAGPipeline
from src.data_loader import load_and_clean_pdf
from src.text_splitter import split_by_article
from src.vector_store import get_or_create_collection,add_documents

st.title("Legal RAG Chatbot")
if 'rag' not in st.session_state:
    load_dotenv('./.env')
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    data_path='./data/raw/158-vbhn-vpqh.pdf'
    collection=get_or_create_collection('./db','legal_database')
    embedder=LegalEmbedding()
    st.session_state.rag=LegalRAGPipeline(collection,embedder,GEMINI_API_KEY)
    st.session_state.messages = []
    if collection.count()==0:
        text=load_and_clean_pdf(data_path)
        chunks=split_by_article(text)
        embeddings=embedder.embed(chunks)   
        add_documents(collection,chunks,embeddings)
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message['content'])
question = st.chat_input("Nhập câu hỏi pháp lý...")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.spinner("Đang xử lý..."):
        answer = st.session_state.rag.ask(question)
        st.session_state.messages.append({"role": "assistant", "content": answer})
    st.rerun() 
