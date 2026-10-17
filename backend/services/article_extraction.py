"""Bounded public article fetching and extraction."""
import ipaddress
import re
import socket
import time
from io import BytesIO
from urllib.parse import urlsplit, urljoin, urlunsplit
import requests
from backend.services.discovery import canonicalize_url

MAX_BYTES = 20 * 1024 * 1024
MAX_CHARS = 500_000
ARXIV = re.compile(r'^/(?:abs|pdf)/((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)(?:\.pdf)?/?$')


def validate_url(url):
    p = urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        raise ValueError('Use a public HTTP or HTTPS article URL without credentials')
    if p.port not in (None, 443 if p.scheme == 'https' else 80):
        raise ValueError('Only standard HTTP and HTTPS ports are supported')
    addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Article URLs must resolve only to public addresses')
    return url


def canonical_article_url(url):
    p = urlsplit(url)
    match = ARXIV.fullmatch(p.path) if p.hostname in ('arxiv.org','www.arxiv.org','export.arxiv.org') else None
    return 'https://arxiv.org/abs/' + match[1] if match else canonicalize_url(url)


def download(url):
    deadline = time.monotonic() + 90
    session = requests.Session()
    session.trust_env = False
    try:
        for _ in range(6):
            validate_url(url)
            # Pin the connection to a validated address to prevent DNS rebinding.
            parts = urlsplit(url)
            addresses = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError('Article destination changed to a private address')
            address = addresses[0][4][0]
            host = f'[{address}]' if ':' in address else address
            pinned = urlunsplit((parts.scheme, host, parts.path, parts.query, ''))
            adapter = requests.adapters.HTTPAdapter()
            if parts.scheme == 'https':
                adapter.init_poolmanager(1, 1, assert_hostname=parts.hostname, server_hostname=parts.hostname)
            session.mount(parts.scheme + '://', adapter)
            with session.get(pinned, stream=True, allow_redirects=False, timeout=(10,20),
                             headers={'Host':parts.hostname, 'User-Agent':'lalaland-research/0.1'}) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers['Location'])
                    continue
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > MAX_BYTES or time.monotonic() > deadline:
                        raise ValueError('Article exceeds download size or time limit')
                return bytes(body), response.headers.get('Content-Type','').lower(), url
        raise ValueError('Too many article redirects')
    finally:
        session.close()


def extract(url):
    from pypdf import PdfReader
    import trafilatura
    canonical = canonical_article_url(url)
    arxiv = canonical.startswith('https://arxiv.org/abs/')
    target = canonical.replace('/abs/','/pdf/') if arxiv else url
    body, content_type, resolved = download(target)
    metadata = {}
    if body.startswith(b'%PDF-'):
        reader = PdfReader(BytesIO(body))
        if len(reader.pages) > 300:
            raise ValueError('PDF exceeds 300 pages')
        sections = []
        count = 0
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or '').replace('\x00', '').strip()
            count += len(text)
            if count > MAX_CHARS:
                raise ValueError('Article exceeds extraction limit; no partial summary was generated')
            if text:
                sections.append({'ref':f'page {i+1}', 'text':text})
        title = str((reader.metadata or {}).get('/Title') or '')
        if arxiv:
            # arXiv stamps include the exact version used, even for unversioned links.
            match = re.search(r'arXiv:\s*([^\s]+v\d+)', ' '.join(s['text'] for s in sections[:2]))
            if not match:
                raise ValueError('Could not determine the arXiv version from the PDF')
            metadata['arxiv_version'] = match[1]
            resolved = 'https://arxiv.org/pdf/' + match[1]
    elif 'html' in content_type:
        document = trafilatura.bare_extraction(body, include_comments=False, include_tables=True)
        if not document:
            raise ValueError('No readable article text found')
        text = (document.text or '').replace('\x00', '')
        title = document.title or ''
        metadata = {'author': document.author, 'date': document.date}
        sections = [{'ref':f'section {i+1}', 'text':part} for i,part in enumerate(text.splitlines()) if part.strip()]
    else:
        raise ValueError('Unsupported article format; provide a PDF or HTML article')
    text = '\n\n'.join(f'[{s["ref"]}]\n{s["text"]}' for s in sections)
    if len(text) < 500:
        raise ValueError('Insufficient full article text; scanned PDFs require OCR, which is not supported')
    if len(text) > MAX_CHARS:
        raise ValueError('Article exceeds extraction limit; no partial summary was generated')
    return dict(title=title.replace('\x00', '').strip() or (sections[0]['text'].splitlines()[0][:250]),
                resolved_url=resolved, metadata=metadata, sections=sections, article_text=text)
