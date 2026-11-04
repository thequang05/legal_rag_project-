from backend.lexical import LexicalIndex, terms


class FakeRegistry:
    def __init__(self, chunks):
        self.chunks = [{'chunk_id': f'd:{i}', 'document_id': 'd', 'page': 1, 'clause': '', 'point': '', **c}
                       for i, c in enumerate(chunks)]

    def all_chunks(self, document_id):
        return self.chunks


def test_terms_fold_diacritics_and_add_bigrams():
    assert 'doi_tuong' in terms('Đối tượng áp dụng') and 'ap_dung' in terms('Đối tượng áp dụng')
    assert terms('ĐỐI TƯỢNG') == terms('doi tuong')
    assert 'cua' not in terms('của')


def test_bm25_ranks_phrase_match_first_and_ignores_question_words():
    index = LexicalIndex(FakeRegistry([
        {'text': 'Điều 1. Phạm vi điều chỉnh', 'article': 'Điều 1'},
        {'text': 'Điều 2. Đối tượng áp dụng', 'article': 'Điều 2'},
        {'text': '1. Tổ chức tín dụng.', 'article': 'Điều 2', 'clause': '1'},
        {'text': 'Điều 3. Giải thích từ ngữ', 'article': 'Điều 3'}]))
    ranked = index.search('Đối tượng áp dụng của Luật này gồm những ai?', ['d'], 3)
    assert ranked[0] == 'd:1'
    # Children inherit the Điều title through their context prefix.
    assert 'd:2' in ranked and 'd:0' not in ranked
    assert index.search('???', ['d'], 3) == [] and index.search('đối tượng', [], 3) == []


def test_invalidate_reloads_chunks():
    registry = FakeRegistry([{'text': 'Điều 1. alpha', 'article': 'Điều 1'}])
    index = LexicalIndex(registry)
    assert index.search('beta', ['d'], 3) == []
    registry.chunks[0]['text'] = 'Điều 1. beta'
    assert index.search('beta', ['d'], 3) == []
    index.invalidate('d')
    assert index.search('beta', ['d'], 3) == ['d:0']
