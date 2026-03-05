import fitz
import re
def load_and_clean_pdf(data_path,start_page=0,num_pages=10):
    try:
        doc = fitz.open(data_path)
    except Exception as e:
        print(f"Error opening PDF: {e}")
        return None
    full_text=""
    for page_num in range(start_page,min(start_page+num_pages,doc.page_count)):
        page=doc.load_page(page_num)
        clip_rect=fitz.Rect(0,50,page.rect.width,page.rect.height-50)
        text=page.get_text("text",clip=clip_rect)
        text = re.sub(r'(?<![.:;])\n', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        full_text+=text + "\n\n"
    return full_text
    
