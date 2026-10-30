#!/usr/bin/env python3
"""Deterministically generate the S02 tiny media goldens and MANIFEST.json.

    python tests/fixtures/media/generate_media.py            # (re)write every file
    python tests/fixtures/media/generate_media.py --check    # regenerate in memory, diff vs disk

Everything except MP3/MP4 is produced with the Python stdlib (struct/zlib/wave/tarfile), so
bytes are identical on every platform. MP3 and MP4 need ffmpeg (bit-exact flags, single
thread); `--check` reports them as "skipped" when ffmpeg is absent rather than failing, and
the committed bytes are still validated structurally by test_fixture_foundation.py.

Not produced: no format was impossible here; OpenEXR is written uncompressed by a minimal
stdlib writer (ffmpeg's EXR encoder is not byte-reproducible run to run on this host).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import wave
import zlib
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
MANIFEST = "MANIFEST.json"
FIXED_MTIME = 1793347200  # 2026-10-30T08:00:00Z


# ----------------------------------------------------------------------------- PNG
def png(width: int, height: int, pixel: Callable[[int, int], tuple[int, ...]], channels: int = 3) -> bytes:
    color_type = {1: 0, 3: 2, 4: 6}[channels]
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            raw.extend(pixel(x, y)[:channels])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def sky(x: int, y: int, w: int, h: int) -> tuple[float, float, float]:
    """A simple linear-light equirect sky: bright sun disc, blue gradient, brown ground."""
    lon = (x + 0.5) / w * 2 * math.pi
    lat = math.pi / 2 - (y + 0.5) / h * math.pi
    if lat < 0:
        return (0.18, 0.12, 0.07)
    base = (0.25 + 0.5 * (1 - lat / (math.pi / 2)), 0.45 + 0.3 * (1 - lat / (math.pi / 2)), 0.9)
    d = math.hypot(lon - math.pi, lat - 0.6)
    if d < 0.25:
        return (40.0, 36.0, 30.0)  # > 1.0: genuinely high dynamic range
    return base


def _tonemap(v: float) -> int:
    return max(0, min(255, round(255 * (v / (1 + v)) ** (1 / 2.2))))


# ----------------------------------------------------------------------------- HDR / EXR
def radiance_hdr(width: int, height: int) -> bytes:
    out = bytearray(b"#?RADIANCE\n# S02 fixture equirect\nFORMAT=32-bit_rle_rgbe\n\n")
    out += f"-Y {height} +X {width}\n".encode()
    for y in range(height):
        for x in range(width):
            r, g, b = sky(x, y, width, height)
            m = max(r, g, b)
            if m < 1e-32:
                out += b"\x00\x00\x00\x00"
                continue
            mant, exp = math.frexp(m)
            scale = mant * 256.0 / m
            out += bytes((int(r * scale), int(g * scale), int(b * scale), exp + 128))
    return bytes(out)


def openexr(width: int, height: int) -> bytes:
    """Minimal single-part scanline OpenEXR, NO_COMPRESSION, FLOAT B/G/R channels."""

    def attr(name: str, typ: str, data: bytes) -> bytes:
        return name.encode() + b"\0" + typ.encode() + b"\0" + struct.pack("<i", len(data)) + data

    chlist = b"".join(c.encode() + b"\0" + struct.pack("<iB3xii", 2, 0, 1, 1) for c in "BGR") + b"\0"
    box = struct.pack("<iiii", 0, 0, width - 1, height - 1)
    header = (attr("channels", "chlist", chlist) + attr("compression", "compression", b"\x00")
              + attr("dataWindow", "box2i", box) + attr("displayWindow", "box2i", box)
              + attr("lineOrder", "lineOrder", b"\x00") + attr("pixelAspectRatio", "float", struct.pack("<f", 1.0))
              + attr("screenWindowCenter", "v2f", struct.pack("<ff", 0, 0))
              + attr("screenWindowWidth", "float", struct.pack("<f", 1.0)) + b"\0")
    head = struct.pack("<ii", 20000630, 2) + header
    lines = []
    for y in range(height):
        px = [sky(x, y, width, height) for x in range(width)]
        data = b"".join(struct.pack(f"<{width}f", *(p[i] for p in px)) for i in (2, 1, 0))  # B, G, R
        lines.append(struct.pack("<ii", y, len(data)) + data)
    table_start = len(head)
    offsets, pos = [], table_start + 8 * height
    for line in lines:
        offsets.append(pos)
        pos += len(line)
    return head + struct.pack(f"<{height}Q", *offsets) + b"".join(lines)


# ----------------------------------------------------------------------------- GLB
def _pad(b: bytes, fill: bytes = b"\0") -> bytes:
    return b + fill * ((4 - len(b) % 4) % 4)


def glb(doc: dict, binary: bytes) -> bytes:
    js = _pad(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode(), b" ")
    bn = _pad(binary)
    total = 12 + 8 + len(js) + 8 + len(bn)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(bn), b"BIN\0") + bn)


class _Buf:
    def __init__(self) -> None:
        self.data = bytearray()
        self.views: list[dict] = []
        self.accessors: list[dict] = []

    def add(self, fmt: str, values: list, comp: int, typ: str, count: int, *, target: int | None = None,
            minmax: tuple | None = None) -> int:
        while len(self.data) % 4:
            self.data.append(0)
        off = len(self.data)
        self.data += struct.pack("<" + fmt * len(values), *values)
        view = {"buffer": 0, "byteOffset": off, "byteLength": len(self.data) - off}
        if target:
            view["target"] = target
        self.views.append(view)
        acc = {"bufferView": len(self.views) - 1, "componentType": comp, "count": count, "type": typ}
        if minmax:
            acc["min"], acc["max"] = list(minmax[0]), list(minmax[1])
        self.accessors.append(acc)
        return len(self.accessors) - 1


CUBE_POS = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
CUBE_IDX = [0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 2, 3, 7, 2, 7, 6, 1, 2, 6, 1, 6, 5, 3, 0, 4, 3, 4, 7]


def static_cube_glb() -> bytes:
    b = _Buf()
    pos = b.add("f", [c for p in CUBE_POS for c in p], 5126, "VEC3", 8, target=34962, minmax=((-1, -1, -1), (1, 1, 1)))
    idx = b.add("H", CUBE_IDX, 5123, "SCALAR", 36, target=34963)
    doc = {"asset": {"version": "2.0", "generator": "S02 generate_media.py"},
           "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "crate"}],
           "meshes": [{"name": "crate", "primitives": [{"attributes": {"POSITION": pos}, "indices": idx, "mode": 4}]}],
           "materials": [{"name": "grey", "pbrMetallicRoughness": {"baseColorFactor": [0.6, 0.6, 0.6, 1]}}],
           "accessors": b.accessors, "bufferViews": b.views, "buffers": [{"byteLength": 0}]}
    doc["meshes"][0]["primitives"][0]["material"] = 0
    doc["buffers"][0]["byteLength"] = len(_pad(bytes(b.data)))
    return glb(doc, bytes(b.data))


def rigged_glb() -> bytes:
    """A two-bone skinned column with two animation clips ("Wave" and "Idle")."""
    b = _Buf()
    pos_list = [(x, y, z) for y in (0.0, 1.0, 2.0) for (x, z) in ((-0.2, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2))]
    pos = b.add("f", [c for p in pos_list for c in p], 5126, "VEC3", 12, target=34962, minmax=((-0.2, 0, -0.2), (0.2, 2, 0.2)))
    idx_list = []
    for ring in (0, 4):
        for s in range(4):
            a, c = ring + s, ring + (s + 1) % 4
            idx_list += [a, c, c + 4, a, c + 4, a + 4]
    idx = b.add("H", idx_list, 5123, "SCALAR", len(idx_list), target=34963)
    # Bottom ring bound to joint 0 (root), upper two rings to joint 1 (upper).
    joints = b.add("B", [v for i in range(12) for v in ((0 if i < 4 else 1), 0, 0, 0)], 5121, "VEC4", 12, target=34962)
    weights = b.add("f", [v for _ in range(12) for v in (1.0, 0.0, 0.0, 0.0)], 5126, "VEC4", 12, target=34962)
    ibm = b.add("f", [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1],
                5126, "MAT4", 2)
    times = b.add("f", [0.0, 0.5, 1.0], 5126, "SCALAR", 3, minmax=((0.0,), (1.0,)))
    rot_wave = b.add("f", [0, 0, 0, 1, 0, 0, math.sin(math.radians(15)), math.cos(math.radians(15)), 0, 0, 0, 1],
                     5126, "VEC4", 3)
    rot_idle = b.add("f", [0, 0, 0, 1, math.sin(math.radians(5)), 0, 0, math.cos(math.radians(5)), 0, 0, 0, 1],
                     5126, "VEC4", 3)
    doc = {"asset": {"version": "2.0", "generator": "S02 generate_media.py"},
           "scene": 0, "scenes": [{"nodes": [0, 1]}],
           "nodes": [{"name": "column", "mesh": 0, "skin": 0},
                     {"name": "root", "children": [2]},
                     {"name": "upper", "translation": [0, 1, 0]}],
           "meshes": [{"name": "column", "primitives": [{"attributes": {"POSITION": pos, "JOINTS_0": joints,
                                                                         "WEIGHTS_0": weights}, "indices": idx}]}],
           "skins": [{"joints": [1, 2], "inverseBindMatrices": ibm, "skeleton": 1}],
           "animations": [
               {"name": "Wave", "samplers": [{"input": times, "output": rot_wave, "interpolation": "LINEAR"}],
                "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}]},
               {"name": "Idle", "samplers": [{"input": times, "output": rot_idle, "interpolation": "LINEAR"}],
                "channels": [{"sampler": 0, "target": {"node": 1, "path": "rotation"}}]}],
           "accessors": b.accessors, "bufferViews": b.views, "buffers": [{"byteLength": len(_pad(bytes(b.data)))}]}
    return glb(doc, bytes(b.data))


# ----------------------------------------------------------------------------- audio
def wav_tone(rate: int = 48000, seconds: float = 0.25, channels: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        n = int(rate * seconds)
        for i in range(n):
            # 480 Hz at 48 kHz: exactly 100 samples per period, so the clip loops seamlessly.
            v = int(12000 * math.sin(2 * math.pi * 480 * i / rate))
            frames += struct.pack("<h", v) * channels
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _ffmpeg(args: list[str], suffix: str) -> bytes | None:
    exe = shutil.which("ffmpeg")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out" + suffix)
        subprocess.run([exe, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *args, out],
                       check=True, capture_output=True)
        return Path(out).read_bytes()


def mp3_tone() -> bytes | None:
    return _ffmpeg(["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=0.3", "-ac", "1",
                    "-c:a", "libmp3lame", "-b:a", "32k", "-bitexact", "-flags", "+bitexact", "-fflags", "+bitexact",
                    "-map_metadata", "-1", "-id3v2_version", "0", "-write_xing", "0"], ".mp3")


def mp4_testsrc() -> bytes | None:
    return _ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=32x32:rate=6:duration=1", "-c:v", "libx264", "-threads", "1",
                    "-preset", "veryfast", "-pix_fmt", "yuv420p", "-x264-params", "threads=1:sliced-threads=0",
                    "-bitexact", "-flags", "+bitexact", "-fflags", "+bitexact", "-map_metadata", "-1",
                    "-movflags", "+faststart"], ".mp4")


# ----------------------------------------------------------------------------- sequences
def _tar(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), FIXED_MTIME, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def sequence_frames() -> list[tuple[str, bytes]]:
    frames = []
    for f in range(4):
        frames.append((f"frame_{f:04d}.png",
                       png(16, 16, lambda x, y, f=f: (255 if (x // 4 + f) % 4 == 0 else 30, 16 * y, 64 * f))))
    return frames


def sequence_tar() -> bytes:
    return _tar(sequence_frames())


def traversal_tar() -> bytes:
    """Hostile archive: a member escaping the extraction root (zip-slip/tar-slip negative fixture)."""
    return _tar([("frame_0000.png", sequence_frames()[0][1]), ("../../escape.txt", b"S02 traversal fixture\n")])


def tar_entries(data: bytes) -> list[dict]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tf:
        return [{"name": m.name, "offset": m.offset, "size": m.size} for m in tf.getmembers() if m.isfile()]


# ----------------------------------------------------------------------------- registry
def _json(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()


def motion_json() -> bytes:
    return _json({"format": "studiotwin-fixture-motion/v1", "fps": 30, "frames": 4, "skeleton": "fixture-biped-2",
                  "clips": [{"name": "walk", "start": 0, "end": 3}],
                  "joints": {"root": [[0, 0, 0], [0, 0.02, 0.1], [0, 0, 0.2], [0, 0.02, 0.3]]}})


def rig_audit_json() -> bytes:
    return _json({"format": "studiotwin-fixture-rig-audit/v1", "riggable": True, "joints": 2, "warnings": []})


def _px(width: int, height: int, fn):
    return lambda x, y: fn(x, y, width, height)


GENERATORS: dict[str, tuple[Callable[[], bytes | None], dict]] = {
    "model/static-cube.glb": (static_cube_glb, {"kind": "glb", "rigged": False}),
    "model/rigged-animated.glb": (rigged_glb, {"kind": "glb", "rigged": True, "clips": ["Wave", "Idle"]}),
    "model/rig-audit.json": (rig_audit_json, {"kind": "json"}),
    "env/equirect-64x32.hdr": (lambda: radiance_hdr(64, 32), {"kind": "hdr", "width": 64, "height": 32}),
    "env/equirect-32x16.exr": (lambda: openexr(32, 16), {"kind": "exr", "width": 32, "height": 16}),
    "env/equirect-64x32.png": (lambda: png(64, 32, _px(64, 32, lambda x, y, w, h: tuple(_tonemap(c) for c in sky(x, y, w, h))))
                               , {"kind": "png", "width": 64, "height": 32, "projection": "equirectangular"}),
    "material/pbr-albedo.png": (lambda: png(16, 16, lambda x, y: (150 + 4 * x, 90 + 2 * y, 60)), {"kind": "png", "role": "basecolor"}),
    "material/pbr-normal.png": (lambda: png(16, 16, lambda x, y: (128, 128, 255)), {"kind": "png", "role": "normal"}),
    "material/pbr-roughness.png": (lambda: png(16, 16, lambda x, y: (180,), channels=1), {"kind": "png", "role": "roughness"}),
    "material/pbr-metalness.png": (lambda: png(16, 16, lambda x, y: (0 if x < 8 else 255,), channels=1), {"kind": "png", "role": "metalness"}),
    "image/concept-64.png": (lambda: png(64, 64, lambda x, y: (4 * x, 4 * y, 128, 255), channels=4), {"kind": "png", "width": 64, "height": 64}),
    "audio/tone-48k.wav": (wav_tone, {"kind": "wav", "rate": 48000, "channels": 2, "seconds": 0.25}),
    "audio/tone-44k.mp3": (mp3_tone, {"kind": "mp3", "needs": "ffmpeg"}),
    "video/testsrc-32.mp4": (mp4_testsrc, {"kind": "mp4", "width": 32, "height": 32, "needs": "ffmpeg"}),
    "motion/walk-clip.json": (motion_json, {"kind": "json"}),
    "sequence/frames-4x16.tar": (sequence_tar, {"kind": "tar", "frames": 4}),
    "sequence/traversal-hostile.tar": (traversal_tar, {"kind": "tar", "hostile": True}),
}

MATERIAL_SET = {"name": "fixture-pbr", "present": ["basecolor", "normal", "roughness", "metalness"],
                "missing": ["height"]}


def build() -> tuple[dict[str, bytes], dict[str, str]]:
    files, skipped = {}, {}
    for rel, (fn, _meta) in GENERATORS.items():
        data = fn()
        if data is None:
            skipped[rel] = "ffmpeg not found"
            continue
        files[rel] = data
    return files, skipped


def manifest_for(files: dict[str, bytes]) -> dict:
    entries = {}
    for rel, (_fn, meta) in GENERATORS.items():
        data = files.get(rel)
        if data is None:
            data = (ROOT / rel).read_bytes()
        entry = dict(meta, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        if meta["kind"] == "tar":
            entry["entries"] = tar_entries(data)
        entries[rel] = entry
    return {"format": "studiotwin-fixture-media/v1", "generator": "tests/fixtures/media/generate_media.py",
            "material_set": MATERIAL_SET, "files": entries,
            "not_produced": [], "notes": "MP3/MP4 need ffmpeg; all other files are stdlib-generated."}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    files, skipped = build()
    manifest = _json(manifest_for(files))
    if args.check:
        report = {"match": [], "differ": [], "skipped": sorted(skipped)}
        for rel, data in list(files.items()) + [(MANIFEST, manifest)]:
            p = ROOT / rel
            (report["match"] if p.is_file() and p.read_bytes() == data else report["differ"]).append(rel)
        print(json.dumps(report))
        return 1 if report["differ"] else 0
    if skipped:
        print(f"refusing to write: {skipped}", file=sys.stderr)
        return 2
    for rel, data in files.items():
        p = ROOT / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (ROOT / MANIFEST).write_bytes(manifest)
    print(json.dumps({"written": sorted(files) + [MANIFEST]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
