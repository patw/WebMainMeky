"""FastAPI service.

Request path is deterministic only. The LLM appears exclusively in /author, which
is meant to run as a background task on logged failures.
"""
from __future__ import annotations

from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from . import author as author_mod
from . import config
from .fetch import FetchError, fetch
from .pipeline import extract as run_extract
from .store import Store

app = FastAPI(title='WebMainMeky', version='0.1.0')
_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


class ExtractIn(BaseModel):
    url: Optional[str] = None
    html: Optional[str] = None
    profile: str = 'canonical'
    fetch_first: bool = True


class ExtractOut(BaseModel):
    url: str
    tier: Optional[str]
    rule_id: Optional[str]
    strategy: Optional[str]
    validated: bool
    needs_authoring: bool
    markdown: str
    validation: Optional[dict]
    signature: dict
    attempts: list
    elapsed_ms: float


class AuthorIn(BaseModel):
    episode_id: Optional[str] = None
    url: Optional[str] = None
    html: Optional[str] = None


class RuleIn(BaseModel):
    signature: str
    level: str = 'fine'
    include_xpaths: list[str]
    exclude_xpaths: list[str] = []
    profile: str = 'canonical'
    url: str = ''
    notes: str = ''
    activate: bool = False


class GoldenIn(BaseModel):
    url: str
    html: str
    markdown: str


class StatusIn(BaseModel):
    status: str


@app.get('/health')
def health():
    return {'ok': True, 'model': config.OPENAI_MODEL, 'base_url': config.OPENAI_BASE_URL}


@app.get('/stats')
def stats():
    return store().stats()


@app.post('/extract', response_model=ExtractOut)
def extract_endpoint(payload: ExtractIn):
    html = payload.html
    url = payload.url or ''
    if not html and url:
        if not payload.fetch_first:
            raise HTTPException(400, 'no html provided and fetch_first=false')
        try:
            html = fetch(url)
        except FetchError as exc:
            raise HTTPException(422, str(exc))
    if not html:
        raise HTTPException(400, 'provide html or url')
    if payload.profile not in ('canonical', 'gt'):
        raise HTTPException(400, 'profile must be canonical or gt')
    res = run_extract(html, url=url, profile=payload.profile, store=store())
    return ExtractOut(**{k: res[k] for k in ExtractOut.model_fields})


@app.get('/rules')
def rules(status: Optional[str] = None, limit: int = 50):
    return {'rules': store().list_rules(status=status, limit=limit)}


@app.post('/rules')
def add_rule(payload: RuleIn):
    rule = store().upsert_rule(signature=payload.signature, level=payload.level,
                               include_xpaths=payload.include_xpaths,
                               exclude_xpaths=payload.exclude_xpaths,
                               provenance='human', profile=payload.profile,
                               url=payload.url, notes=payload.notes, support=1)
    if payload.activate:
        rule = store().set_rule_status(rule['_id'], 'active')
    return rule


@app.post('/rules/{rule_id}/status')
def rule_status(rule_id: str, payload: StatusIn):
    try:
        return store().set_rule_status(rule_id, payload.status)
    except Exception as exc:
        raise HTTPException(404, str(exc))


@app.get('/episodes/pending')
def pending(limit: int = 20):
    return {'episodes': store().pending_authoring(limit=limit)}


@app.post('/author')
def author(payload: AuthorIn, background: BackgroundTasks):
    """Run rule authoring. With episode_id it pulls the stored page reference;
    with html it authors immediately (useful for testing)."""
    s = store()
    if payload.html:
        ep = {'url': payload.url or '', 'reasons': ['manual'], 'markdown_preview': ''}
        return author_mod.author_rule(s, ep, payload.html)
    if payload.episode_id:
        background.add_task(_author_from_episode, payload.episode_id)
        return {'queued': True, 'episode_id': payload.episode_id}
    raise HTTPException(400, 'provide episode_id or html')


def _author_from_episode(episode_id: str):
    """Background job: re-fetch the episode URL and author a rule for it."""
    s = store()
    ep = s.episodes.find_one({'_id': episode_id})
    if not ep:
        return {'ok': False, 'reason': 'no_such_episode'}
    url = ep.get('url', '')
    if not url:
        return {'ok': False, 'reason': 'episode_has_no_url'}
    try:
        html = fetch(url)
    except FetchError as exc:
        return {'ok': False, 'reason': str(exc)}
    ep = dict(ep)
    ep['markdown_preview'] = ''
    return author_mod.author_rule(s, ep, html)


@app.post('/golden')
def add_golden(payload: GoldenIn):
    return store().add_golden(payload.url, payload.html, payload.markdown)


@app.get('/golden')
def get_golden(limit: int = 50):
    rows = store().golden_pages(limit=limit)
    return {'golden': [{'url': r.get('url'), 'chars': len(r.get('markdown', ''))}
                       for r in rows]}


@app.post('/compact')
def compact():
    s = store()
    out = {}
    for name in ('rules', 'episodes', 'golden', 'signatures'):
        getattr(s, name).compact()
        out[name] = getattr(s, name).stats()
    return out
