from __future__ import annotations

import re
from textwrap import dedent

import requests
from langsmith import traceable
from opentelemetry import trace

from backend.config import Settings
from backend.services.ollama_queue import inference_slot
from backend.services import vllm


def _remove_reasoning(text: str) -> str:
    without_reasoning = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)
    without_reasoning = re.sub(r"<think>.*$", "", without_reasoning, flags=re.IGNORECASE | re.DOTALL)
    return without_reasoning.strip()


@traceable(name="granite.summarize", run_type="llm")
def _generate_summary(
    prompt: str,
    *,
    ollama_base_url: str,
    ollama_model: str,
    ollama_timeout_seconds: int,
) -> str:
    response = requests.post(
        f"{ollama_base_url.rstrip('/')}/api/generate",
        json={
            "model": ollama_model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"temperature": 0.2},
        },
        timeout=ollama_timeout_seconds,
    )
    response.raise_for_status()

    payload = response.json()
    summary = _remove_reasoning(payload.get("response", ""))
    if not summary:
        raise RuntimeError("Ollama returned an empty summary")

    return summary


@traceable(name="vllm.summarize", run_type="llm",
           process_inputs=lambda inputs: {'prompt': inputs['prompt'], 'model': inputs['settings'].rss_model})
def _generate_vllm_summary(prompt, settings):
    summary = _remove_reasoning(vllm.generate(
        settings, settings.rss_model, prompt, timeout=settings.ollama_timeout_seconds, max_tokens=768,
    ))
    if not summary:
        raise ValueError('vLLM returned an empty summary')
    return summary


class OllamaSummarizer:
    """RSS summarizer; the historical class name is retained for callers."""
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tracer = trace.get_tracer(__name__)

    def summarize(
        self,
        *,
        source_name: str,
        article_title: str,
        article_url: str,
        article_text: str,
    ) -> str:
        prompt = dedent(
            f"""
            You are writing a daily research briefing.
            Summarize the article below in 2-4 concise sentences.
            Focus on the main claim, the important supporting details, and why it matters.
            Do not use markdown, bullets, or hedging.

            Source: {source_name}
            Title: {article_title}
            URL: {article_url}

            Article:
            {article_text[:6000]}
            """
        ).strip()

        with self.tracer.start_as_current_span("granite.summarize") as span:
            span.set_attribute("gen_ai.system", self.settings.inference_provider)
            span.set_attribute("gen_ai.request.model", self.settings.rss_model)
            span.set_attribute("article.source_name", source_name)
            span.set_attribute("article.url", article_url)
            span.set_attribute("gen_ai.request.prompt_chars", len(prompt))

            with inference_slot(self.settings):
                summary = self._generate(prompt, source_name, article_url)

            span.set_attribute("gen_ai.response.chars", len(summary))
            span.add_event("granite.response", {"summary_preview": summary[:240]})
            return summary

    def _generate(self, prompt, source_name, article_url):
        if self.settings.inference_provider == 'vllm':
            return _generate_vllm_summary(prompt, self.settings)
        return _generate_summary(
            prompt,
            ollama_base_url=self.settings.ollama_base_url,
            ollama_model=self.settings.ollama_model,
            ollama_timeout_seconds=self.settings.ollama_timeout_seconds,
            langsmith_extra={
                "metadata": {
                    "article.source_name": source_name,
                    "article.url": article_url,
                    "gen_ai.request.prompt_chars": len(prompt),
                },
                "tags": ["ollama", "granite"],
            },
        )
