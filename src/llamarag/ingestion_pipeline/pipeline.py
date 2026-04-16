from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter

from llamarag.local_model.embed_model import embed_model
from llamarag.storage.vector_store import vector_store


def ingestion_pipeline() -> IngestionPipeline:

    pipeline = IngestionPipeline(
        transformations=[
            SentenceSplitter(chunk_size=512, chunk_overlap=20),
            embed_model,
        ],
        vector_store=vector_store,
    )

    return pipeline