"""RAG 全局配置 —— 所有参数一处改，消除各模块各自写死的问题。"""

# ── 检索 ──
RETRIEVAL_TOP_K = 12          # 向量检索候选 chunk 数
MAX_CONTEXT_CHARS = 1000000     # 拼入 prompt 的上下文上限（字符）

# ── 混合检索（Hybrid Search）──
HYBRID_ENABLED = True           # 是否启用混合检索（向量 + BM25 融合）
HYBRID_VECTOR_WEIGHT = 0.7      # 向量检索权重（0-1）
HYBRID_BM25_WEIGHT = 0.3        # BM25 权重（0-1），两者之和应为 1
HYBRID_RRF_K = 60               # RRF 融合参数（越大越平滑，典型值 60）

# ── 分块 ──
MIN_HEADING_LEVEL = 3         # 在哪个标题级别切 section（3 = ###）
MAX_SECTION_SIZE = 10000      # section 强制切分阈值（设大则不强制切）
CHUNK_SIZE = 500              # 字符级 chunk 大小
CHUNK_OVERLAP = 50            # chunk 重叠量
SECTION_OVERLAP = 200         # section 强制切分时的重叠量
