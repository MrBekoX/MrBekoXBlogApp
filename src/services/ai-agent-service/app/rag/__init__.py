"""RAG (Retrieval-Augmented Generation) module for article chat."""

from app.rag.embeddings import EmbeddingService
from app.rag.chunker import TextChunker
from app.infrastructure.vector_store.chroma_adapter import ChromaAdapter
from app.rag.retriever import Retriever

# ChromaAdapter is the single vector store implementation
VectorStore = ChromaAdapter

__all__ = ["EmbeddingService", "TextChunker", "VectorStore", "ChromaAdapter", "Retriever"]
