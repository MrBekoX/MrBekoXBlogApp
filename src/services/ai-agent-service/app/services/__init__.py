"""Application services - Business logic orchestration layer."""

from importlib import import_module

__all__ = [
    "ContentCleanerService",
    "AnalysisService",
    "SeoService",
    "RagService",
    "IndexingService",
    "ChatService",
    "MessageProcessorService",
]

_SERVICE_MODULES = {
    "ContentCleanerService": "app.services.content_cleaner",
    "AnalysisService": "app.services.analysis_service",
    "SeoService": "app.services.seo_service",
    "RagService": "app.services.rag_service",
    "IndexingService": "app.services.indexing_service",
    "ChatService": "app.services.chat_service",
    "MessageProcessorService": "app.services.message_processor_service",
}


def __getattr__(name: str):
    """Lazily resolve services to avoid hard import coupling at package import time."""
    module_path = _SERVICE_MODULES.get(name)
    if not module_path:
        raise AttributeError(f"module 'app.services' has no attribute '{name}'")
    module = import_module(module_path)
    return getattr(module, name)
