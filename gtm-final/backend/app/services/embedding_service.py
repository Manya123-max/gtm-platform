"""
embedding_service — re-exports EmbeddingService from services package.
Actual implementation lives in app/services/__init__.py (hash-based, 0 deps).
"""
from app.services import EmbeddingService

__all__ = ["EmbeddingService"]
