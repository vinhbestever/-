import pytest
from app.services.embedding_service import EmbeddingService


@pytest.fixture(scope="module")
def service():
    return EmbeddingService()


class TestEmbedding:
    def test_embed_returns_list_of_floats(self, service):
        vec = service.embed("Xin chào, tôi muốn hỏi về dịch vụ")
        assert isinstance(vec, list)
        assert len(vec) > 0
        assert all(isinstance(v, float) for v in vec)

    def test_embed_dimension_matches_config(self, service):
        vec = service.embed("Hello world")
        assert len(vec) == service.dims

    def test_embed_batch(self, service):
        texts = [
            "Tôi muốn khiếu nại",
            "Cảm ơn dịch vụ rất tốt",
            "Hẹn gọi lại ngày mai",
        ]
        vecs = service.embed_batch(texts)
        assert len(vecs) == 3
        assert all(len(v) == service.dims for v in vecs)

    def test_similar_texts_have_high_cosine(self, service):
        v1 = service.embed("Tôi muốn khiếu nại về đơn hàng bị hỏng")
        v2 = service.embed("Đơn hàng của tôi bị lỗi, tôi muốn phàn nàn")
        v3 = service.embed("Thời tiết hôm nay đẹp quá")

        cos_similar = sum(a * b for a, b in zip(v1, v2))
        cos_different = sum(a * b for a, b in zip(v1, v3))

        assert cos_similar > cos_different

    def test_normalized_vectors(self, service):
        vec = service.embed("Test normalization")
        magnitude = sum(v * v for v in vec) ** 0.5
        assert abs(magnitude - 1.0) < 0.01
