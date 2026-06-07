from __future__ import annotations

from textwrap import dedent

import requests
from opentelemetry import trace

from backend.config import Settings


class OllamaSummarizer:
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
            span.set_attribute("gen_ai.system", "ollama")
            span.set_attribute("gen_ai.request.model", self.settings.ollama_model)
            span.set_attribute("article.source_name", source_name)
            span.set_attribute("article.url", article_url)
            span.set_attribute("gen_ai.request.prompt_chars", len(prompt))

            response = requests.post(
                f"{self.settings.ollama_base_url.rstrip('/')}/api/generate",
                json={
                    "model": self.settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2},
                },
                timeout=self.settings.ollama_timeout_seconds,
            )
            response.raise_for_status()

            payload = response.json()
            summary = payload.get("response", "").strip()
            if not summary:
                raise RuntimeError("Ollama returned an empty summary")

            span.set_attribute("gen_ai.response.chars", len(summary))
            span.add_event(
                "granite.response",
                {
                    "summary_preview": summary[:240],
                },
            )

            return summary
