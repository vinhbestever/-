import structlog
from sentence_transformers import SentenceTransformer

from app.config import settings

logger = structlog.get_logger(__name__)


class EmbeddingService:
    def __init__(self):
        self._model: SentenceTransformer | None = None

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading embedding model", model=settings.embedding_model)
            self._model = SentenceTransformer(settings.embedding_model)
            logger.info("Embedding model loaded", dims=self._model.get_sentence_embedding_dimension())
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._get_model()
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vectors]

    @property
    def dims(self) -> int:
        return self._get_model().get_sentence_embedding_dimension()


embedding_service = EmbeddingService()
