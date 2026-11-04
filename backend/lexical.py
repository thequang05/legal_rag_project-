"""In-memory BM25 over stored chunks, used beside vector search (hybrid retrieval).

Terms are diacritic-folded Vietnamese syllables plus adjacent-syllable bigrams, so 'đối tượng áp dụng'
matches the phrase and a question typed without accents still matches. Chunks are indexed together with
their Điều/Khoản context, like the embeddings.
"""
import math
import re
import unicodedata
from collections import Counter, defaultdict

from .parsing import build_contexts

STOPWORDS = frozenset('''va cua la cac co nhung duoc trong cho khi voi mot de nay nao gi ai bao nhieu the nhu
thi ma hay hoac tai tu theo ve den bi se da dang gom gia sao'''.split())
WORD = re.compile(r'\w+', re.UNICODE)


def fold(text):
    text = text.replace('đ', 'd').replace('Đ', 'D')
    return ''.join(c for c in unicodedata.normalize('NFD', text) if not unicodedata.combining(c)).lower()


def terms(text):
    words = WORD.findall(fold(text))
    out = [w for w in words if w not in STOPWORDS]
    out += [f'{a}_{b}' for a, b in zip(words, words[1:]) if not (a in STOPWORDS and b in STOPWORDS)]
    return out


class LexicalIndex:
    K1, B = 1.2, 0.75

    def __init__(self, registry):
        self.registry = registry
        self._docs = {}

    def invalidate(self, document_id=None):
        if document_id is None:
            self._docs.clear()
        else:
            self._docs.pop(document_id, None)

    def _load(self, document_id):
        if document_id not in self._docs:
            chunks = self.registry.all_chunks(document_id)
            postings, lengths = defaultdict(list), []
            for position, (chunk, context) in enumerate(zip(chunks, build_contexts(chunks))):
                counts = Counter(terms(f"{context} {chunk['text']}"))
                lengths.append(sum(counts.values()))
                for term, tf in counts.items():
                    postings[term].append((position, tf))
            self._docs[document_id] = ([c['chunk_id'] for c in chunks], lengths, postings)
        return self._docs[document_id]

    def search(self, question, document_ids, limit):
        """Chunk ids ranked by BM25; empty when the question has no usable terms."""
        query = set(terms(question))
        if not query or not document_ids:
            return []
        loaded = [self._load(d) for d in document_ids]
        total = sum(len(ids) for ids, _, _ in loaded)
        average = (sum(sum(lengths) for _, lengths, _ in loaded) / total) if total else 0
        if not total or not average:
            return []
        idf = {}
        for term in query:
            df = sum(len(postings.get(term, ())) for _, _, postings in loaded)
            if df:
                idf[term] = math.log(1 + (total - df + 0.5) / (df + 0.5))
        scores = {}
        for ids, lengths, postings in loaded:
            for term, weight in idf.items():
                for position, tf in postings.get(term, ()):
                    norm = tf + self.K1 * (1 - self.B + self.B * lengths[position] / average)
                    scores[ids[position]] = scores.get(ids[position], 0.0) + weight * tf * (self.K1 + 1) / norm
        return sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:limit]
