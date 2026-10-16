"""Rule / episode / golden storage on moofile. Self-contained: one directory,
three .bson files, no server.

Writes are serialized with a process-local lock (moofile serializes writes across
processes with an advisory lock; FastAPI serves requests on a thread pool, so we
also serialize inside the process).
"""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

from moofile import Collection, DocumentNotFoundError

from . import config

RULE_STATUS = ('candidate', 'active', 'retired')


def html_hash(html_str: str) -> str:
    return hashlib.sha256((html_str or '').encode('utf-8', 'replace')).hexdigest()[:16]


def _now() -> float:
    return time.time()


class Store:
    def __init__(self, data_dir: Path = None):
        self.data_dir = Path(data_dir or config.DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        self.rules = Collection(
            str(self.data_dir / 'rules.bson'),
            indexes=['signature', 'status', 'level', 'provenance'])
        self.episodes = Collection(
            str(self.data_dir / 'episodes.bson'),
            indexes=['signature_fine', 'signature_coarse', 'tier', 'needs_authoring',
                     'rule_id', 'validated'])
        self.golden = Collection(str(self.data_dir / 'golden.bson'), indexes=['url'])
        self.signatures = Collection(
            str(self.data_dir / 'signatures.bson'),
            indexes=['fine', 'coarse'])

    def close(self):
        for c in (self.rules, self.episodes, self.golden, self.signatures):
            c.close()

    # ------------------------------------------------------------------ rules
    def find_rule(self, keys: list[str], flags: list[str] = None) -> dict | None:
        """Best active rule for a signature: fine level first, then coarse, then family.
        Among candidates, rules whose landmark flags match the page rank higher."""
        want = set(flags or [])
        with self._lock:
            for key in keys:
                if not key:
                    continue
                rows = self.rules.find({'signature': key, 'status': 'active'}).to_list()
                rows = [r for r in rows if r.get('confidence', 0) >= config.MIN_CONFIDENCE]
                if not rows:
                    continue
                rows.sort(key=lambda r: (
                    -len(want & set(r.get('flags') or [])),
                    -r.get('support', 0),
                    -r.get('confidence', 0)))
                return rows[0]
        return None

    def upsert_rule(self, signature: str, level: str, include_xpaths: list[str],
                    exclude_xpaths: list[str] = (), provenance: str = 'induced',
                    profile: str = 'gt', url: str = '', notes: str = '',
                    support: int = 0, flags: list[str] = None) -> dict:
        """Insert or merge a rule by (signature, selector set).

        support counts *validated outcomes recorded via record_outcome*, not the
        insert itself - so the promotion bar measures real re-validations."""
        key = tuple(sorted(include_xpaths or []))
        with self._lock:
            existing = self.rules.find({'signature': signature}).to_list()
            for r in existing:
                if tuple(sorted(r.get('include_xpaths') or [])) == key:
                    self.rules.update_one({'_id': r['_id']}, set={
                        'support': r.get('support', 0) + support,
                        'last_seen': _now(),
                        'url_example': url or r.get('url_example', ''),
                    })
                    return self.rules.find_one({'_id': r['_id']})
            doc = self.rules.insert({
                'signature': signature,
                'level': level,
                'flags': list(flags or []),
                'include_xpaths': list(include_xpaths or []),
                'exclude_xpaths': list(exclude_xpaths or []),
                'profile': profile,
                'support': support,
                'fails': 0,
                'confidence': 0.0,
                'status': 'candidate',
                'provenance': provenance,
                'url_example': url,
                'notes': notes,
                'created_at': _now(),
                'updated_at': _now(),
                'last_seen': _now(),
            })
            return doc

    def record_outcome(self, rule_id: str, ok: bool):
        with self._lock:
            rule = self.rules.find_one({'_id': rule_id})
            if not rule:
                return None
            support = rule.get('support', 0) + (1 if ok else 0)
            fails = rule.get('fails', 0) + (0 if ok else 1)
            total = support + fails
            conf = (support / total) if total else 0.0
            status = rule.get('status', 'candidate')
            # Promotion bar depends on provenance: rules induced from human labels
            # earn promotion on one validated page; LLM-authored rules need two.
            bar = {'induced': 1, 'human': 1}.get(rule.get('provenance'), 2)
            bar = max(bar, 1)
            if status == 'candidate' and support >= bar and conf >= config.MIN_CONFIDENCE:
                status = self._promotion_status(rule)
            if total >= 10 and conf < 0.35:
                status = 'retired'
            self.rules.update_one({'_id': rule_id}, set={
                'support': support, 'fails': fails, 'confidence': round(conf, 4),
                'status': status, 'updated_at': _now(), 'last_seen': _now()})
            return self.rules.find_one({'_id': rule_id})

    def _promotion_status(self, rule: dict) -> str:
        """Golden regression gate: a rule may not go active if it demonstrably
        mangles a golden page that shares its layout signature.

        Rules that match no golden page are judged by provenance: label-induced
        rules carry annotation evidence and may promote; LLM-authored rules may not,
        because one page of self-validation is not enough evidence.
        """
        if not config.GOLDEN_GATE or self.golden.count({}) == 0:
            return 'active'
        from . import golden
        chk = golden.check_rule(self, rule, limit=config.GOLDEN_LIMIT)
        self.rules.update_one({'_id': rule['_id']}, set={
            'golden_checked': chk['checked'],
            'golden_mean': chk['mean'],
            'golden_worst': chk['worst']})
        if chk['checked'] == 0:
            return 'active' if rule.get('provenance') in ('induced', 'human') else 'candidate'
        return 'active' if chk['ok'] else 'candidate'

    def set_rule_status(self, rule_id: str, status: str) -> dict:
        if status not in RULE_STATUS:
            raise ValueError(f'status must be one of {RULE_STATUS}')
        with self._lock:
            self.rules.update_one({'_id': rule_id},
                                  set={'status': status, 'updated_at': _now()})
            return self.rules.find_one({'_id': rule_id})

    def list_rules(self, status: str = None, limit: int = 50) -> list[dict]:
        with self._lock:
            flt = {'status': status} if status else {}
            return self.rules.find(flt).sort('support', descending=True).limit(limit).to_list()

    def rule_stats(self) -> dict:
        with self._lock:
            out = {}
            for s in RULE_STATUS:
                out[s] = self.rules.count({'status': s})
            out['total'] = self.rules.count({})
            return out

    # -------------------------------------------------------------- episodes
    def log_episode(self, **fields) -> dict:
        with self._lock:
            fields.setdefault('created_at', _now())
            return self.episodes.insert(fields)

    def pending_authoring(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return (self.episodes.find({'needs_authoring': True})
                    .sort('created_at', descending=True).limit(limit).to_list())

    # ---------------------------------------------------------------- golden
    def add_golden(self, url: str, html_str: str, markdown: str) -> dict:
        with self._lock:
            if self.golden.exists({'url': url}):
                self.golden.delete_one({'url': url})
            return self.golden.insert({'url': url, 'html': html_str,
                                       'markdown': markdown, 'created_at': _now()})

    def golden_pages(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return self.golden.find({}).limit(limit).to_list()

    # ------------------------------------------------------------ signatures
    def note_signature(self, fine: str, coarse: str, url: str, shape: str):
        with self._lock:
            row = self.signatures.find({'fine': fine}).first() if fine else None
            if row:
                self.signatures.update_one({'_id': row['_id']},
                                           set={'n_seen': row.get('n_seen', 0) + 1,
                                                'last_seen': _now()})
                return row
            return self.signatures.insert({
                'fine': fine, 'coarse': coarse, 'url_example': url,
                'shape': shape, 'n_seen': 1, 'created_at': _now(), 'last_seen': _now()})

    def stats(self) -> dict:
        with self._lock:
            return {
                'rules': self.rule_stats(),
                'episodes': self.episodes.count({}),
                'episodes_needs_authoring': self.episodes.count({'needs_authoring': True}),
                'golden': self.golden.count({}),
                'signatures': self.signatures.count({}),
                'data_dir': str(self.data_dir),
            }
