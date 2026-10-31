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
        # Stable job-ID order, then nonempty direct metadata takes precedence.
        related = sorted((k,r) for k,r in rows.items()
                         if k == identifier or identifier in r.get('outputAssetIds',[]))
        related.sort(key=lambda pair: pair[0] == identifier)
        rec = {}
        for _, row in related:
            for key, value in row.items():
                if key in ('sourceAssetIds','outputAssetIds'):
                    rec[key] = sorted(set(rec.get(key,[])) | set(value))
                elif value:
                    rec[key] = value
        parents = [{'id':s, 'relation':'source'} for s in rec.get('sourceAssetIds',[])]
        parents += [{'id':k, 'relation':'job'} for k,_ in related if k != identifier]
        children = [{'id':k, 'relation':'derived'} for k,r in sorted(rows.items()) if identifier in r.get('sourceAssetIds',[])]
        children += [{'id':a,'relation':'output'} for a in rec.get('outputAssetIds',[]) if a != identifier]
        label = rec.get('prompt') or rec.get('tool')
        return {'id':identifier, 'record':rec, 'parents':parents, 'children':children,
                'made_from':f'Made from {label}' if label else None, 'recorded':bool(rec)}
