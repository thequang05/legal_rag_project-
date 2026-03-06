# Legal RAG Assistant

A retrieval-augmented generation (RAG) system for answering questions based on Vietnamese legal documents. The system extracts text from PDF files, splits content by article, stores embeddings in a vector database, and uses Gemini to generate grounded answers.

## Prerequisites

- Python 3.11+
- A valid `GEMINI_API_KEY` from Google AI Studio
- A Vietnamese legal PDF placed at `./data/raw/` (default file: `158-vbhn-vpqh.pdf`)

## Installation

```bash
# Clone the repository
git clone https://github.com/thequang05/legal_rag_project-.git
cd legal_rag_project-

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create a .env file and set your API key
echo "GEMINI_API_KEY=your_api_key_here" > .env
```

## Usage

### Streamlit web interface

```bash
python -m streamlit run app.py
```

The app initializes the vector store on first run (this may take a few minutes while embedding the document). Subsequent runs load the existing database from `./db`.

### Command-line interface

```bash
python main.py
```

Starts an interactive Q&A loop in the terminal. Enter `1` to exit.

## Architecture

```
legal_rag_project-/
├── app.py                  # Streamlit demo app
├── main.py                 # CLI entry point
├── requirements.txt
├── configs/
│   └── prompts.py          # Prompt templates (LEGAL_QA_PROMPT, QUERY_REWRITE_PROMPT)
├── data/
│   └── raw/                # Input PDF files
├── db/                     # ChromaDB persistent storage (auto-generated)
└── src/
    ├── data_loader.py       # PDF extraction via PyMuPDF
    ├── text_splitter.py     # Article-level chunking (splits on "Dieu X.")
    ├── embedding.py         # Sentence embedding (multilingual-MiniLM-L12-v2)
    ├── vector_store.py      # ChromaDB collection management (cosine similarity)
    └── rag_pipeline.py      # Retrieve-then-generate pipeline using Gemini 2.5 Flash
```

**Processing flow:**

```
PDF -> load_and_clean_pdf -> split_by_article -> LegalEmbedding.embed
     -> ChromaDB upsert -> LegalRAGPipeline.retrieve (cosine, threshold=0.5)
     -> Gemini 2.5 Flash -> answer
```


