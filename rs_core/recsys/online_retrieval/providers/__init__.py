from __future__ import annotations

from rs_core.recsys.online_retrieval.providers.pool500_fallback import Pool500FallbackProvider
from rs_core.recsys.online_retrieval.providers.postgres_category import PostgresCategoryProvider
from rs_core.recsys.online_retrieval.providers.postgres_item_neighbors import PostgresItemNeighborsProvider
from rs_core.recsys.online_retrieval.providers.postgres_popular import PostgresPopularProvider
from rs_core.recsys.online_retrieval.providers.postgres_usercf import PostgresUserCFProvider
from rs_core.recsys.online_retrieval.providers.qdrant_two_tower import QdrantTwoTowerProvider
from rs_core.recsys.online_retrieval.providers.semantic_token import SemanticTokenProvider
from rs_core.recsys.online_retrieval.providers.semantic_vector import SemanticVectorProvider

__all__ = [
    "Pool500FallbackProvider",
    "PostgresCategoryProvider",
    "PostgresItemNeighborsProvider",
    "PostgresPopularProvider",
    "PostgresUserCFProvider",
    "QdrantTwoTowerProvider",
    "SemanticTokenProvider",
    "SemanticVectorProvider",
]
