from functools import lru_cache
from os import getenv
from threading import Lock

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DIMENSION = 384
_model_lock = Lock()


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=MODEL, threads=2, cache_dir=getenv("EMBEDDING_CACHE_DIR"))


def embed(texts: list[str]) -> list[str]:
    """Encode a batch as pgvector's text representation for bound SQL parameters."""
    with _model_lock:
        model = _model()
    return [str(vector.tolist()) for vector in model.embed(texts, batch_size=32)]
