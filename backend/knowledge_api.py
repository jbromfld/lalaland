"""HTTP retrieval client: scoring and filtering remain in lassy."""
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.config import load_settings

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class KnowledgeQuery(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=100)
    filters: dict = Field(default_factory=dict)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


@router.post("/query")
def query_knowledge(request: KnowledgeQuery):
    settings = load_settings()
    if not settings.knowledge_service_url:
        raise HTTPException(503, "Set KNOWLEDGE_SERVICE_URL to enable shared retrieval")
    payload = request.model_dump()
    payload["filters"].setdefault("collection", ["lalaland-rss", "lalaland-corpus"])
    try:
        response = requests.post(f"{settings.knowledge_service_url}/query", json=payload,
                                 timeout=settings.knowledge_timeout_seconds)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        raise HTTPException(502, "Shared retrieval service is unavailable") from exc
