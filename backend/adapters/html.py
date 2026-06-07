from __future__ import annotations

import requests
from bs4 import BeautifulSoup


REQUEST_HEADERS = {"User-Agent": "ResearchBriefing/1.0"}


class HTMLAdapter:
    def discover(self, url: str) -> list[str]:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        return [anchor["href"] for anchor in soup.select("a[href]")]

    def extract_article(self, url: str) -> dict[str, str]:
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title_node = soup.find("h1") or soup.find("title")
        paragraphs = [
            paragraph.get_text(" ", strip=True)
            for paragraph in soup.select("article p, main p, p")
            if paragraph.get_text(" ", strip=True)
        ]
        text = "\n".join(paragraphs[:40]).strip()

        return {
            "title": title_node.get_text(" ", strip=True) if title_node else "",
            "text": text[:6000],
        }
