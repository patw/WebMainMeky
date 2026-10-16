"""URL -> HTML. Deliberately small and defensive: this is the least interesting
part of the system and the part most likely to hang, so it is capped hard.

No JavaScript rendering here - pages that need JS should be posted to /extract as
raw HTML by a renderer service.
"""
from __future__ import annotations

import re

import requests

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
MAX_BYTES = 6_000_000
TIMEOUT = 20
ALLOWED = ('text/html', 'application/xhtml', 'text/plain', 'application/xml')


class FetchError(Exception):
    pass


def fetch(url: str, timeout: int = TIMEOUT, max_bytes: int = MAX_BYTES) -> str:
    if not re.match(r'^https?://', url, re.I):
        raise FetchError('only http(s) URLs are supported')
    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True,
                         headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
    except requests.RequestException as exc:
        raise FetchError(f'fetch_failed:{type(exc).__name__}') from exc

    if r.status_code >= 400:
        raise FetchError(f'http_{r.status_code}')

    ctype = (r.headers.get('content-type') or '').lower()
    if ctype and not any(a in ctype for a in ALLOWED):
        raise FetchError(f'unsupported_content_type:{ctype.split(";")[0]}')

    body = r.content[:max_bytes]
    if not r.encoding or r.encoding.lower() in ('iso-8859-1', 'latin-1'):
        r.encoding = r.apparent_encoding or 'utf-8'
    try:
        return body.decode(r.encoding, 'replace')
    except LookupError:
        return body.decode('utf-8', 'replace')
