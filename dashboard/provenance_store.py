"""S11 lineage: atomic DAG merge, internal attribution, closed wire projection.

Pattern adapted from elevenlabs-sound-effects/provenance.py (MIT).
Copyright (c) 2026 Nous Research
Internal source/concept columns are intentionally never added to wire schemas.
"""
from collections import deque
from .ipc_client import redaction
from .store import CONTRACT, RETENTION


class ProvenanceStore:
    def __init__(self, store):
        self.store = store

    def _rows(self, scope_id, generation):
        rows = self.store.connection.execute('SELECT parent,child,relation,parent_kind,child_kind,source,concept_id FROM s11_provenance WHERE scope_id=? AND generation=? AND seen>? ORDER BY parent,child,relation,source,concept_id LIMIT 20001',
            (scope_id,generation,self.store.now()-RETENTION)).fetchall()
        if len(rows)>20000:
            raise redaction.BoundaryRefused()
        return rows

    @staticmethod
    def _dag(rows):
        kinds, adjacency, indegree = {}, {}, {}
        for parent,child,relation,pk,ck,*_ in rows:
            for identifier,kind in ((parent,pk),(child,ck)):
                if identifier in kinds and kinds[identifier] != kind:
                    raise redaction.BoundaryRefused()
                kinds[identifier] = kind
                adjacency.setdefault(identifier,set())
                indegree.setdefault(identifier,0)
            if child not in adjacency[parent]:
                adjacency[parent].add(child)
                indegree[child] += 1
        queue = deque(k for k,v in indegree.items() if not v)
        visited = 0
        while queue:
            node = queue.popleft(); visited += 1
            for child in adjacency[node]:
                indegree[child] -= 1
                if not indegree[child]: queue.append(child)
        if visited != len(kinds):
            raise redaction.BoundaryRefused()
        return kinds

    def _insert(self, rows, *, scope_id, generation):
        with self.store.transaction(scope_id,generation):
            existing = self._rows(scope_id,generation)
            if len(existing)+len(rows)>20000:
                raise redaction.BoundaryRefused()
            self._dag(existing+rows)
            self.store.connection.executemany('INSERT OR REPLACE INTO s11_provenance VALUES (?,?,?,?,?,?,?,?,?,?)',
                [(scope_id,generation,*r,self.store.now()) for r in rows])

    def record(self, request, *, scope_id, generation, concept_id=None):
        v = self.store.validate('ProvenanceRecordRequestV1',request,scope_id,generation).to_json()
        if concept_id is not None:
            self.store.validate('UuidV1',concept_id,scope_id,generation)
        relation = v.get('relation','generated-from')
        job = v['jobId']
        rows = [(a,job,relation,'asset','job','local-recorded',concept_id or '') for a in set(v['sourceAssetIds'])]
        rows += [(job,a,'output-of','job','asset','local-recorded',concept_id or '') for a in set(v['outputAssetIds'])]
        result = self.store.validate('ProvenanceRecordedV1',dict(contract=CONTRACT,edgeCount=len(rows)),scope_id,generation)
        self._insert(rows,scope_id=scope_id,generation=generation)
        return result

    def merge_server(self, lineage, *, scope_id, generation, concept_id=None):
        v = self.store.validate('LineageV1',lineage,scope_id,generation).to_json()
        if concept_id is not None:
            self.store.validate('UuidV1',concept_id,scope_id,generation)
        kinds = {n['id']:n['kind'] for n in v['nodes']}
        if len(kinds) != len(v['nodes']) or (v['nodes'] and kinds.get(v['root']) != 'asset'):
            raise redaction.BoundaryRefused()
        rows = []
        for e in v['edges']:
            if e['parent'] not in kinds or e['child'] not in kinds:
                raise redaction.BoundaryRefused()
            rows.append((e['parent'],e['child'],e['relation'],kinds[e['parent']],kinds[e['child']],'server-reported',concept_id or ''))
        self._insert(rows,scope_id=scope_id,generation=generation)
        # Preserve an isolated server root and its truncation indication too.
        self.store.put('lineage',v['root'],v,scope_id=scope_id,generation=generation)

    def records(self, *, scope_id, generation):
        with self.store.transaction(scope_id,generation):
            return [dict(zip(('parent','child','relation','parent_kind','child_kind','source','concept_id'),r)) for r in self._rows(scope_id,generation)]

    def lineage(self, asset, *, scope_id, generation):
        self.store.validate('UuidV1',asset,scope_id,generation)
        cached = self.store.get('lineage',asset,scope_id=scope_id,generation=generation)
        with self.store.transaction(scope_id,generation):
            rows = self._rows(scope_id,generation)
            kinds = self._dag(rows)
            adjacency = {}
            edges = sorted(set(r[:3] for r in rows))
            for parent,child,relation in edges:
                adjacency.setdefault(parent,[]).append((child,1))
                adjacency.setdefault(child,[]).append((parent,-1))
            depths = {asset:0} if asset in kinds or (cached and cached.to_json()['nodes']) else {}
            queue = deque(depths)
            truncated = bool(cached and cached.to_json()['truncated'])
            while queue:
                node = queue.popleft()
                for other,step in adjacency.get(node,[]):
                    if other in depths: continue
                    depth = depths[node]+step
                    if abs(depth)>12 or len(depths)>=100:
                        truncated = True
                        continue
                    depths[other] = depth
                    queue.append(other)
            selected = [dict(parent=p,child=c,relation=r) for p,c,r in edges if p in depths and c in depths]
            if len(selected)>400: truncated = True
            value = dict(contract=CONTRACT,root=asset,nodes=[dict(kind=kinds.get(n,'asset'),id=n,depth=d) for n,d in depths.items()],
                         edges=selected[:400],truncated=truncated)
            return self.store.validate('LineageV1',value,scope_id,generation)
