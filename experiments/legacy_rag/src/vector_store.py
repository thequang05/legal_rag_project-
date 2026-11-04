import chromadb

def get_or_create_collection(db_path,collection_name):
    if not db_path:
        raise ValueError("db_path must not be empty")
    if not collection_name:
        raise ValueError("collection_name must not be empty")
    client=chromadb.PersistentClient(path=db_path)
    collection=client.get_or_create_collection(name=collection_name,configuration={"hnsw": {
            "space": "cosine"
        }})
    return collection
def add_documents(collection,chunks,embeddings):
    if not chunks:
        raise ValueError("chunks must not be empty")
    if not embeddings:
        raise ValueError("embeddings must not be empty")
    ids=['doc_'+ str(i) for i in range(len(chunks))]
    collection.upsert(ids=ids,embeddings=embeddings,documents=chunks)