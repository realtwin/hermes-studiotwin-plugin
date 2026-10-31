"""Profile-local Made from records; partial writes merge instead of erasing lineage."""
from __future__ import annotations

from .store import STATE_LOCK, read_json, write_json


class ProvenanceStore:
    def __init__(self, root):
        self.path = root / 'provenance.json'

    def rows(self):
        rows = read_json(self.path, {})
        return {k:v for k,v in rows.items() if isinstance(v,dict)} if isinstance(rows,dict) else {}

    def record(self, identifier, record):
        with STATE_LOCK:
            rows = self.rows()
            merged = dict(rows.get(identifier, {}))
            merged.update(record)
            rows[identifier] = merged
            write_json(self.path, rows)
            return merged

    def details(self, identifier):
        rows = self.rows()
        related = [(k,r) for k,r in rows.items() if k == identifier or identifier in r.get('outputAssetIds',[])]
        rec = related[0][1] if related else {}
        parents = [{'id':s, 'relation':'source'} for s in rec.get('sourceAssetIds',[])]
        if related and related[0][0] != identifier:
            parents.append({'id':related[0][0], 'relation':'job'})
        children = [{'id':k, 'relation':'derived'} for k,r in rows.items() if identifier in r.get('sourceAssetIds',[])]
        children += [{'id':a,'relation':'output'} for a in rec.get('outputAssetIds',[]) if a != identifier]
        label = rec.get('prompt') or rec.get('tool')
        return {'id':identifier, 'record':rec, 'parents':parents, 'children':children,
                'made_from':f'Made from {label}' if label else None, 'recorded':bool(rec)}
