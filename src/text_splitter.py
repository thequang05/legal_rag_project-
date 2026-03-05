import re
from typing import List
def split_by_article(text):
    chunks = re.split(r'(?=\bĐiều\s+\d+\.)', text)
    valid_chunks=[c.strip() for c in chunks if len(c.strip())>50]
    return valid_chunks
