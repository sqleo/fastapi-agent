"""Milvus 向量库与 LlamaIndex ``StorageContext`` 单例。"""

from llama_index.core import StorageContext
from llama_index.vector_stores.milvus import MilvusVectorStore
from llama_index.vector_stores.milvus.utils import BM25BuiltInFunction

from configs.env import env_config

# 须与 ``env_config.embedding_dimensions``、HTTP /embeddings 返回维数一致。
_EMBED_DIM = env_config.embedding_dimensions

hnsw_index_config = {
    "index_type": "HNSW",  # 指定使用 HNSW
    "metric_type": "COSINE",  # 推荐：COSINE（与大多数 embedding 模型匹配），也可选 "IP" 或 "L2"
    "params": {
        "M": 30,  # 每节点最大连接数（默认 30）
        "efConstruction": 200,  # 构建时候选邻居数量（默认 ~100-300）
    },
}


# ====================== 检索配置（推荐值） ======================
# 须为「内层」HNSW 参数。LlamaIndex 在 hybrid/dense 检索里会再包一层 ``params``；
hnsw_search_config = {"ef": 64}


# ====================== 创建 MilvusVectorStore ======================

vector_store = MilvusVectorStore(
    uri=env_config.milvus_uri,
    dim=_EMBED_DIM,
    collection_name="collection_hybrid",
    similarity_metric="cosine",
    # overwrite=True,  # 开发时 True（重建集合），生产环境改成 False
    index_config=hnsw_index_config,
    search_config=hnsw_search_config,
    enable_sparse=True,
    # 稀疏侧用 Milvus 内置 BM25；dense 向量维与全局 HTTP 嵌入一致
    sparse_embedding_function=BM25BuiltInFunction(),
    # 可选：混合检索时的 reranker
    hybrid_ranker="RRFRanker",  # 默认是 RRFRanker（Reciprocal Rank Fusion）
    # hybrid_ranker="WeightedRanker",
    # hybrid_ranker_params={"weights": [1.0, 0.5]}, # dense:1.0, sparse:0.5，可调整权重
)


storage_context = StorageContext.from_defaults(vector_store=vector_store)
