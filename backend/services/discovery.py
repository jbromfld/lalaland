from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_PREFIXES = ("utm_", "fbclid", "gclid")


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.startswith(TRACKING_QUERY_PREFIXES)
    ]

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            urlencode(filtered_query, doseq=True),
            "",
        )
    )


def filter_new_urls(urls: list[str], seen_urls: set[str]) -> list[str]:
    return [url for url in urls if url not in seen_urls]
