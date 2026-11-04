"""Conservative line-anchored Điều/Khoản/Điểm parsing with exact page offsets."""
import re
import pymupdf as fitz

ARTICLE = re.compile(r'^\s*(Điều\s+\d+[a-zđ]?)(?:[.\s]|$)', re.IGNORECASE)
CLAUSE = re.compile(r'^\s*(?:Khoản\s+)?(\d+)[.)]\s+', re.IGNORECASE)
PAGE_NUMBER = re.compile(r'^\d{1,4}$')
POINT = re.compile(r'^\s*([a-zđ])[)]\s+', re.IGNORECASE)


def validate_pdf(path, max_pages):
    try:
        with fitz.open(path) as pdf:
            if not pdf.is_pdf:
                raise ValueError('Chỉ hỗ trợ PDF.')
            if pdf.needs_pass:
                raise ValueError('PDF có mật khẩu chưa được hỗ trợ.')
            if not 0 < pdf.page_count <= max_pages:
                raise ValueError(f'PDF phải có từ 1 đến {max_pages} trang.')
            return pdf.page_count
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('File PDF không hợp lệ hoặc bị hỏng.') from exc


def extract_chunks(path, max_pages=500, chunk_chars=700, overlap=100):
    page_count = validate_pdf(path, max_pages)
    chunks = []
    article = clause = point = ''
    with fitz.open(path) as pdf:
        for page_number, page in enumerate(pdf, start=1):
            text = page.get_text('text', sort=True)
            if not text.strip():
                raise ValueError(f'Trang {page_number} không có văn bản đọc được; cần OCR trước khi nạp.')
            sections = []
            start = offset = 0
            for line in text.splitlines(keepends=True):
                heading, numbered, letter = ARTICLE.match(line), CLAUSE.match(line), POINT.match(line)
                boundary = heading or (article and numbered) or (article and clause and letter)
                if boundary:
                    if offset > start:
                        sections.append((start, offset, article, clause, point))
                    start = offset
                    if heading:
                        article, clause, point = heading.group(1), '', ''
                    elif numbered:
                        clause, point = numbered.group(1), ''
                    else:
                        point = letter.group(1).lower()
                offset += len(line)
            sections.append((start, len(text), article, clause, point))
            for section_start, section_end, art, cl, pt in sections:
                position = section_start
                while position < section_end:
                    end = min(position + chunk_chars, section_end)
                    if end < section_end:
                        boundary = text.rfind(' ', position + chunk_chars // 2, end)
                        if boundary > position:
                            end = boundary
                    raw = text[position:end]
                    left = position + len(raw) - len(raw.lstrip())
                    right = end - (len(raw) - len(raw.rstrip()))
                    if right > left and not PAGE_NUMBER.match(text[left:right]):
                        chunks.append({'text':text[left:right], 'page':page_number, 'article':art,
                                       'clause':cl, 'point':pt, 'start_char':left, 'end_char':right,
                                       'paragraph_id':f'p{page_number}:{section_start}'})
                    if end == section_end:
                        break
                    position = max(position + 1, end - overlap)
    if not chunks:
        raise ValueError('PDF không có nội dung văn bản; cần OCR.')
    return page_count, chunks


def build_contexts(chunks, title_chars=120, lead_chars=200):
    """Context prefix per chunk (Điều title, Khoản lead-in), used only for embedding.

    Stored text and offsets are untouched; the prefix just lets short Khoản/Điểm
    chunks be retrieved by the question they answer. Chunks must be in document order.
    """
    contexts, title, lead, lead_key = [], '', '', None
    for chunk in chunks:
        text, article, clause, point = chunk['text'], chunk.get('article', ''), chunk.get('clause', ''), chunk.get('point', '')
        is_heading = bool(article) and not clause and not point and ARTICLE.match(text)
        if is_heading:
            title, lead, lead_key = text.split('\n', 1)[0].strip()[:title_chars], '', None
        elif not article:
            title, lead, lead_key = '', '', None
        elif clause and not point and CLAUSE.match(text):
            lead, lead_key = text[:lead_chars].strip(), (article, clause)
        parts = []
        if title and not is_heading:
            parts.append(title)
        if point and lead and lead_key == (article, clause):
            parts.append(lead)
        contexts.append(' | '.join(parts))
    return contexts
