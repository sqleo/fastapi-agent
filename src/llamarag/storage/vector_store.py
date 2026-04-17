from llama_index.core import StorageContext

from llama_index.vector_stores.milvus import MilvusVectorStore

from llama_index.vector_stores.milvus.utils import BM25BuiltInFunction

from configs.env import env_config
from llamarag.local_model.embed_model import dim


hnsw_index_config = {
    "index_type": "HNSW",  # 指定使用 HNSW
    "metric_type": "COSINE",  # 推荐：COSINE（与大多数 embedding 模型匹配），也可选 "IP" 或 "L2"
    "params": {
        "M": 30,  # 每节点最大连接数（默认 30）
        "efConstruction": 200,  # 构建时候选邻居数量（默认 ~100-300）
    },
}


# ====================== 检索配置（推荐值） ======================

hnsw_search_config = {"params": {"ef": 64}}  # 查询时候选列表大小（默认 64）


# ====================== 创建 MilvusVectorStore ======================

vector_store = MilvusVectorStore(
    uri=env_config.milvus_uri,
    dim=dim,  # 与 dense 嵌入一致（bge-small-zh-v1.5 为 512）
    collection_name="collection_hybrid",
    overwrite=True,  # 开发时 True（重建集合），生产环境改成 False
    index_config=hnsw_index_config,
    search_config=hnsw_search_config,
    enable_sparse=True,
    # 稀疏侧用 Milvus 内置 BM25（不依赖 FlagEmbedding / bge-m3）；dense 仍用 bge-small-zh-v1.5
    sparse_embedding_function=BM25BuiltInFunction(),
    # 可选：混合检索时的 reranker
    hybrid_ranker="RRFRanker",  # 默认是 RRFRanker（Reciprocal Rank Fusion）
    # hybrid_ranker="WeightedRanker",
    # hybrid_ranker_params={"weights": [1.0, 0.5]}, # dense:1.0, sparse:0.5，可调整权重
)


storage_context = StorageContext.from_defaults(vector_store=vector_store)
