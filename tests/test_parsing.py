from backend.parsing import extract_chunks
from backend.documents import Registry
from test_api import pdf_bytes


def test_long_text_is_bounded_and_keeps_page(tmp_path):
    path = tmp_path / "law.pdf"
    path.write_bytes(pdf_bytes("This is capital. " * 20, pages=2))
    pages, chunks = extract_chunks(path, chunk_chars=100, overlap=20)
    assert pages == 2
    assert {c["page"] for c in chunks} == {1, 2}
    assert all(0 < len(c["text"]) <= 100 for c in chunks)


def test_headings_and_inline_references(tmp_path):
    import pymupdf as fitz
    path = tmp_path / "law.pdf"
    # Embed a Unicode font so extraction retains Vietnamese article headings.
    font_path = '/System/Library/Fonts/Supplemental/Arial.ttf'
    if not __import__('pathlib').Path(font_path).exists():
        import pytest
        pytest.skip("Unicode font not installed")
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_font(fontname="arial", fontfile=font_path)
        page.insert_text((50, 70), "Điều 1. Tiêu đề\nNội dung dẫn chiếu Điều 2. trong câu.\nĐiều 2. Tiêu đề tiếp\nNội dung.", fontname="arial")
        pdf.new_page().insert_text((50, 70), "Continuation")
        pdf.save(path)
    _, chunks = extract_chunks(path)
    assert [c["article"] for c in chunks] == ["Điều 1", "Điều 2", "Điều 2"]


def test_registry_pagination(tmp_path):
    registry = Registry(tmp_path / "registry.sqlite3")
    for i in range(4):
        registry.insert(str(i), f"{i}.pdf", str(i), 10)
    assert len(registry.list(2, 0)) == 2
    assert len(registry.list(2, 3)) == 1


def test_build_contexts_adds_article_title_and_clause_lead_in_only_for_children():
    from backend.parsing import build_contexts
    chunks = [
        {'text': 'Điều 2. Điều kiện cấp phép', 'article': 'Điều 2', 'clause': '', 'point': ''},
        {'text': '1. Được cấp phép khi đáp ứng các điều kiện sau đây:', 'article': 'Điều 2', 'clause': '1', 'point': ''},
        {'text': 'b) Có vốn điều lệ tối thiểu;', 'article': 'Điều 2', 'clause': '1', 'point': 'b'},
        {'text': '2. Hồ sơ nộp trực tiếp.', 'article': 'Điều 2', 'clause': '2', 'point': ''},
        {'text': 'Điều 3. Thời hạn', 'article': 'Điều 3', 'clause': '', 'point': ''},
        {'text': 'a) Mười ngày;', 'article': 'Điều 3', 'clause': '1', 'point': 'a'},
    ]
    assert build_contexts(chunks) == [
        '',
        'Điều 2. Điều kiện cấp phép',
        'Điều 2. Điều kiện cấp phép | 1. Được cấp phép khi đáp ứng các điều kiện sau đây:',
        'Điều 2. Điều kiện cấp phép',
        '',
        'Điều 3. Thời hạn']


def test_page_number_only_chunks_are_dropped(tmp_path):
    import pymupdf
    path = tmp_path / "n.pdf"
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 100), "Dieu 1. Body text here")
        page.insert_text((300, 800), "64")
        pdf.save(path)
    _, chunks = extract_chunks(path)
    assert all(c["text"] != "64" for c in chunks)
