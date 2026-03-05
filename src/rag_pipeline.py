from google import genai
from typing import List
class LegalRAGPipeline:
    def __init__(self,vector_db_collection,gemini_api_key):
        self.collection=vector_db_collection
        self.client = genai.Client(api_key=gemini_api_key)
        self.model_name='gemini-2.5-flash'
        
