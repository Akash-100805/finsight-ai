import os
import uuid
import logging
from typing import List, Dict, Any, Optional
logger = logging.getLogger("qdrant_service")

class QdrantService:
    def __init__(self):
        self.collection_name = os.getenv("QDRANT_COLLECTION", "financial_news")
        self.vector_size = 1024  # BGE-Large dimensions
        self.client = None
        self._init_qdrant()

    def _init_qdrant(self):
        """Initializes Qdrant client with graceful fallback hierarchy: Local Docker -> In-Memory."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            api_key = os.getenv("QDRANT_API_KEY")
            endpoint_url = os.getenv("QDRANT_ENDPOINT_URL")
            host = os.getenv("QDRANT_HOST", "localhost")
            port = int(os.getenv("QDRANT_PORT", 6333))

            connected = False
            # 1. Try Cloud if API key present
            if endpoint_url and api_key and not api_key.startswith("your_"):
                try:
                    logger.info(f"Connecting to Qdrant Cloud: {endpoint_url}")
                    self.client = QdrantClient(url=endpoint_url, api_key=api_key, timeout=3.0)
                    self.client.get_collections()
                    connected = True
                except Exception as e:
                    logger.warning(f"Cloud Qdrant connection failed: {e}")

            # 2. Try Local Docker Server
            if not connected:
                try:
                    logger.info(f"Connecting to local Qdrant server: {host}:{port}")
                    self.client = QdrantClient(host=host, port=port, timeout=2.0)
                    self.client.get_collections()
                    connected = True
                except Exception as e:
                    logger.info(f"Local Qdrant server unreachable ({e}). Using Qdrant in-memory vector database mode.")

            # 3. Fallback to In-Memory Qdrant Engine
            if not connected:
                self.client = QdrantClient(":memory:")

            # Ensure collection exists
            self._ensure_collection(Distance, VectorParams)

        except Exception as e:
            logger.warning(f"Failed to initialize Qdrant engine ({e}).")
            self.client = None

    def _ensure_collection(self, Distance, VectorParams):
        if not self.client:
            return
        try:
            collections = [c.name for c in self.client.get_collections().collections]
            if self.collection_name not in collections:
                logger.info(f"Creating Qdrant collection: {self.collection_name} (size={self.vector_size})")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE)
                )
        except Exception as e:
            logger.warning(f"Error checking/creating Qdrant collection: {e}")

    def upsert_article_vector(
        self,
        article_id: int,
        vector: List[float],
        payload: Dict[str, Any]
    ) -> str:
        """Upserts dense BGE vector + article payload into Qdrant database."""
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"article_{article_id}"))
        
        if self.client:
            try:
                from qdrant_client.models import PointStruct
                self.client.upsert(
                    collection_name=self.collection_name,
                    points=[
                        PointStruct(
                            id=point_id,
                            vector=vector,
                            payload=payload
                        )
                    ]
                )
                logger.info(f"Successfully stored vector for article {article_id} in Qdrant.")
                return point_id
            except Exception as e:
                logger.warning(f"Error upserting vector to Qdrant: {e}")
        
        return point_id

    def search_similar_articles(
        self,
        query_vector: List[float],
        sector_filter: Optional[str] = None,
        limit: int = 5,
        exclude_article_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Performs vector similarity search in Qdrant with optional payload filter."""
        results = []
        if self.client:
            try:
                from qdrant_client.models import Filter, FieldCondition, MatchValue

                query_filter = None
                if sector_filter:
                    query_filter = Filter(
                        must=[
                            FieldCondition(
                                key="sector",
                                match=MatchValue(value=sector_filter)
                            )
                        ]
                    )

                # Fetch a few extra results when we need to exclude the source article,
                # since Qdrant doesn't know about self-exclusion up front.
                fetch_limit = limit + 1 if exclude_article_id is not None else limit

                search_res = []
                if hasattr(self.client, "query_points"):
                    res_obj = self.client.query_points(
                        collection_name=self.collection_name,
                        query=query_vector,
                        query_filter=query_filter,
                        limit=fetch_limit
                    )
                    search_res = res_obj.points
                elif hasattr(self.client, "search"):
                    search_res = self.client.search(
                        collection_name=self.collection_name,
                        query_vector=query_vector,
                        query_filter=query_filter,
                        limit=fetch_limit
                    )

                for hit in search_res:
                    payload_data = getattr(hit, "payload", {}) or {}
                    if exclude_article_id is not None and payload_data.get("article_id") == exclude_article_id:
                        continue
                    res_dict = dict(payload_data)
                    res_dict["score"] = round(float(getattr(hit, "score", 0.85)), 4)
                    results.append(res_dict)
                    if len(results) >= limit:
                        break

                return results
            except Exception as e:
                logger.warning(f"Error searching vectors in Qdrant: {e}")

        return results

# Singleton instance
qdrant_service = QdrantService()