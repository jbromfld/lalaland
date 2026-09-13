from backend.services.discovery import canonicalize_url, filter_new_urls


def test_canonicalize_url_lowercases_scheme_and_host():
    assert canonicalize_url("HTTPS://Example.com/Path") == "https://example.com/Path"


def test_canonicalize_url_strips_trailing_slash():
    assert canonicalize_url("https://example.com/path/") == "https://example.com/path"


def test_canonicalize_url_root_path_becomes_slash():
    assert canonicalize_url("https://example.com") == "https://example.com/"


def test_canonicalize_url_removes_tracking_params():
    url = "https://example.com/path?utm_source=x&fbclid=y&gclid=z&keep=1"
    assert canonicalize_url(url) == "https://example.com/path?keep=1"


def test_canonicalize_url_is_idempotent():
    url = "https://example.com/path?utm_source=x&keep=1"
    once = canonicalize_url(url)
    assert canonicalize_url(once) == once


def test_filter_new_urls_excludes_seen():
    urls = ["https://a", "https://b", "https://c"]
    seen = {"https://b"}
    assert filter_new_urls(urls, seen) == ["https://a", "https://c"]


def test_filter_new_urls_empty_seen_returns_all():
    urls = ["https://a", "https://b"]
    assert filter_new_urls(urls, set()) == urls
