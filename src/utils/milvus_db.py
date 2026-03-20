import os
from typing import Optional

from dotenv import load_dotenv
from langchain_milvus import Milvus

from utils.embedding_init import create_embeddings

load_dotenv()

MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "MILVUS_COLLECTION")
MILVUS_DIM = int(os.getenv("MILVUS_DIM", "1024"))


class MilvusService:
    def __init__(self):
        self._milvus_vector_store: Optional[Milvus] = None
        self.embeddings = create_embeddings()

    def get_vector_store(self):
        if not self._milvus_vector_store:
            self._milvus_vector_store = Milvus(
                connection_args={
                    "uri": MILVUS_URI
                },
                embedding_function=self.embeddings,
                dim=MILVUS_DIM,
                collection_name=MILVUS_COLLECTION,
                similarity="IP",
                consistency_level="Strong",
                drop_old=True,
            )
        return self._milvus_vector_store
