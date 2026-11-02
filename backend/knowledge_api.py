"""HTTP retrieval client: scoring and filtering remain in lassy."""
import requests
from dataclasses import replace
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.config import load_settings
from backend.services.knowledge_agent import evidence_chunks, synthesize
from backend.services.corpus_summary import installed_models

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def enabled_settings():
    settings = load_settings()
    if not settings.knowledge_active:
        raise HTTPException(503, 'Knowledge is disabled. Set KNOWLEDGE_ENABLED=true and KNOWLEDGE_SERVICE_URL to enable it.')
    return settings


class KnowledgeQuery(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    mode: Literal['chunks', 'summary'] = 'chunks'
    model: str | None = Field(default=None, min_length=1, max_length=200)
    top_k: int = Field(default=5, ge=1, le=100)
    filters: dict = Field(default_factory=dict)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


@router.get('/models')
def knowledge_models():
    settings = enabled_settings()
    try:
        installed = installed_models(settings)
        warning = None if settings.knowledge_model in installed else 'Configured default model is not installed. Select an installed text-generation model or install the default in Ollama.'
        return {'default_model': settings.knowledge_model, 'models': installed, 'error': None, 'warning': warning}
    except (requests.RequestException, ValueError, KeyError):
        return {'default_model': settings.knowledge_model, 'models': [],
                'error': 'Ollama model discovery unavailable; you can still use the configured default.'}


@router.post("/query")
def query_knowledge(request: KnowledgeQuery):
    settings = enabled_settings()
    if request.mode == 'summary' and request.model is not None:
        try:
            installed = installed_models(settings)
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise HTTPException(503, 'Could not validate model: Ollama model discovery unavailable') from exc
        if request.model not in installed:
            raise HTTPException(422, 'Selected model is not installed on the configured Ollama server')
        settings = replace(settings, knowledge_model=request.model)
    payload = request.model_dump(exclude={'mode', 'model'})
    payload["filters"].setdefault("collection", ["lalaland-rss", "lalaland-corpus"])
    try:
        response = requests.post(f"{settings.knowledge_service_url}/query", json=payload,
                                 timeout=settings.knowledge_timeout_seconds)
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        raise HTTPException(502, "Shared retrieval service is unavailable") from exc
    if request.mode == 'chunks':
        return result
    chunks = evidence_chunks(result.get('chunks', []))
    if not chunks:
        return {**result, 'chunks': [], 'summary': 'No matching evidence was found. Try another question.',
                'model': None}
    try:
        summary = synthesize(settings, request.query, chunks)
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(502, 'Knowledge agent could not generate an answer. Try chunk mode or check the configured Ollama model.') from exc
    return {**result, 'chunks': chunks, 'summary': summary, 'model': settings.knowledge_model}
