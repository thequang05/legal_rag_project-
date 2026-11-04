"""Optional cross-encoder reranking of retrieved chunks."""
import logging
from threading import Lock

logger = logging.getLogger(__name__)


class Reranker:
    def __init__(self, model_name, max_length=256):
        self.model_name = model_name
        self.max_length = max_length
        self._model = None
        self._failed = False
        self._lock = Lock()

    def scores(self, question, texts):
        """Relevance score per text (higher is better), or None when the model is unavailable."""
        if self._failed or not texts:
            return None
        with self._lock:
            try:
                if self._model is None:
                    from sentence_transformers import CrossEncoder
                    self._model = CrossEncoder(self.model_name, max_length=self.max_length)
                return [float(score) for score in self._model.predict([(question, text) for text in texts])]
            except Exception:
                # Retrieval still works without reranking; do not retry a broken model on every request.
                logger.exception('Reranker unavailable; continuing without reranking')
                self._failed = True
                return None
