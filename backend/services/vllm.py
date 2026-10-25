"""HTTP adapter for a separately managed vLLM OpenAI-compatible server."""
import requests


class IncompleteGenerationError(ValueError):
    """The server stopped before completing its response."""


def _headers(settings):
    return {"Authorization": f"Bearer {settings.vllm_api_key}"} if settings.vllm_api_key else {}


def installed_models(settings):
    response = requests.get(f'{settings.vllm_base_url.rstrip("/")}/models',
                            headers=_headers(settings), timeout=10)
    response.raise_for_status()
    body = response.json()
    models = body.get('data') if isinstance(body, dict) else None
    if not isinstance(models, list) or any(
        not isinstance(model, dict) or not isinstance(model.get('id'), str) or not model['id']
        for model in models
    ):
        raise ValueError('vLLM returned an invalid model list')
    return sorted({model['id'] for model in models})


def generate(settings, model, prompt, *, timeout, max_tokens, schema=None):
    payload = {
        'model': model, 'messages': [{'role': 'user', 'content': prompt}],
        'stream': False, 'temperature': 0.2, 'max_tokens': max_tokens,
    }
    if schema is not None:
        payload['response_format'] = {
            'type': 'json_schema',
            'json_schema': {'name': 'briefing', 'strict': True, 'schema': schema},
        }
    response = requests.post(f'{settings.vllm_base_url.rstrip("/")}/chat/completions',
                             json=payload, headers=_headers(settings), timeout=timeout)
    response.raise_for_status()
    body = response.json()
    choices = body.get('choices') if isinstance(body, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError('vLLM returned an invalid generation response')
    choice = choices[0]
    if choice.get('finish_reason') == 'length':
        raise IncompleteGenerationError(
            f'vLLM returned an incomplete response (output_budget={max_tokens}). '
            'For final briefings, increase CORPUS_FINAL_NUM_PREDICT or request a shorter briefing.'
        )
    message = choice.get('message')
    if choice.get('finish_reason') != 'stop' or not isinstance(message, dict):
        raise ValueError('vLLM returned an invalid generation response')
    content = message.get('content')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('vLLM returned an empty response')
    return content
