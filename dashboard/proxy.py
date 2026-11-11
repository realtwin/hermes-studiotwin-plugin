"""HTTP byte ranges for local media; bounded bodies cross host isolation as bytes."""
import re
from fastapi import HTTPException, Response


def byte_range(header, size):
    if header is None:
        return 0, size - 1, 200
    match = re.fullmatch(r'bytes=([0-9]{0,20})-([0-9]{0,20})', header)
    headers = {'Accept-Ranges':'bytes', 'Content-Range':f'bytes */{size}'}
    if not match or not any(match.groups()) or size == 0:
        raise HTTPException(416, 'invalid byte range', headers=headers)
    first, last = match.groups()
    if first:
        start, end = int(first), int(last) if last else size - 1
    else:
        start, end = max(0, size - int(last)), size - 1
    if start >= size or end < start or (not first and int(last) == 0):
        raise HTTPException(416, 'unsatisfiable byte range', headers=headers)
    return start, min(end, size - 1), 206


def binary_response(source, size, mime, range_header=None):
    start, end, status = byte_range(range_header, size)
    source.seek(start)
    data = source.read(max(0, end - start + 1))
    headers = {'Accept-Ranges':'bytes', 'X-Content-Type-Options':'nosniff', 'Cache-Control':'no-store'}
    if status == 206:
        headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    return Response(data, status_code=status, media_type=mime, headers=headers)
