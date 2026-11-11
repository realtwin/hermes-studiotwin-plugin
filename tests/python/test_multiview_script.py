"""Real anonymous-pipe Chrome multiview contracts; no paid services."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'skills/studiotwin/scripts/render_multiview.mjs'
MEDIA = ROOT / 'tests/fixtures/media/model'
CHROME = os.environ.get('STUDIOTWIN_PREVIEW_CHROME', '/opt/google/chrome/chrome')
NAMES = ['front', 'right', 'back', 'left', 'three_quarter', 'top']


def run(*args):
    result = subprocess.run(['node', str(SCRIPT), *map(str, args)], capture_output=True, text=True, timeout=180)
    assert len(result.stdout.splitlines()) == 1, result.stdout + result.stderr
    return result, json.loads(result.stdout)


@pytest.mark.parametrize('model', ['static-cube.glb', 'rigged-animated.glb'])
@pytest.mark.parametrize('views', [4, 6])
@pytest.mark.parametrize('shading', ['textured', 'clay', 'normals', 'wireframe'])
def test_real_multiview(tmp_path, model, views, shading):
    assert shutil.which('node') and Path(CHROME).is_file()
    source = MEDIA / model
    original = source.read_bytes()
    sheet = tmp_path / 'sheet.png'
    split = tmp_path / 'tiles'
    result, data = run(source, '--out', sheet, '--split-dir', split, '--views', views,
                       '--shading', shading, '--tile-size', 128, '--transparent', '--no-labels', '--chrome', CHROME)
    assert result.returncode == 0, data
    assert set(data) == {'ok', 'sheet', 'views', 'split_files', 'shading', 'width', 'height', 'bytes', 'yaw_offset_deg'}
    assert data['yaw_offset_deg'] == 0
    assert data['ok'] and data['sheet'] == str(sheet)
    assert data['views'] == NAMES[:views]
    assert data['shading'] == shading
    assert (data['width'], data['height']) == (128 * (views // 2), 256)
    assert data['bytes'] == sheet.stat().st_size
    assert set(data['split_files']) == set(NAMES[:views])
    with Image.open(sheet) as image:
        assert image.size == (data['width'], data['height'])
        assert image.mode == 'RGBA'
        assert image.getpixel((0, 0))[3] == 0
        for i, name in enumerate(NAMES[:views]):
            with Image.open(data['split_files'][name]) as tile:
                assert tile.size == (128, 128)
                assert max(ImageStat.Stat(tile).var[:3]) > 10
                assert tile.getchannel('A').getextrema() == (0, 255)
                crop = image.crop(((i % (views//2))*128, (i // (views//2))*128,
                                   (i % (views//2)+1)*128, (i // (views//2)+1)*128))
                assert ImageChops.difference(crop, tile).getbbox() is None
    assert source.read_bytes() == original


@pytest.mark.parametrize('args', [[], ['--views', '5'], ['--views', 'NaN'], ['--shading', 'bad'],
    ['--tile-size', 'NaN'], ['--tile-size', '0'], ['--tile-size', '128.5'], ['--tile-size', '4096'],
    ['--out', 'bad.jpg'], ['--unknown'], ['--out'], ['--views', '--transparent']])
def test_invalid_arguments(args):
    result, data = run(*([MEDIA/'static-cube.glb'] if args else []), *args)
    assert result.returncode != 0 and data['ok'] is False


def test_no_clobber(tmp_path):
    source = tmp_path/'source.glb'
    source.write_bytes((MEDIA/'static-cube.glb').read_bytes())
    original = source.read_bytes()
    for alias in [source, tmp_path/'hard.png', tmp_path/'sym.png']:
        if alias.name == 'hard.png': os.link(source, alias)
        if alias.name == 'sym.png': alias.symlink_to(source)
        result, data = run(source, '--out', alias)
        assert result.returncode != 0 and data['ok'] is False
        assert source.read_bytes() == original
    output = tmp_path/'existing.png'
    output.write_bytes(b'keep')
    result, data = run(source, '--out', output)
    assert result.returncode != 0 and 'exists' in data['error']
    assert output.read_bytes() == b'keep'
    splits = tmp_path/'splits'; splits.mkdir()
    (splits/'front.png').write_bytes(b'keep')
    result, data = run(source, '--out', tmp_path/'new.png', '--split-dir', splits)
    assert result.returncode != 0 and 'exists' in data['error']
    assert not (tmp_path/'new.png').exists()
    assert (splits/'front.png').read_bytes() == b'keep'


def test_labels_and_determinism(tmp_path):
    images = []
    for name, flags in [('a', []), ('b', []), ('unlabelled', ['--no-labels'])]:
        out = tmp_path/f'{name}.png'
        result, data = run(MEDIA/'static-cube.glb', '--out', out, '--tile-size', 128,
                           '--views', 6, '--chrome', CHROME, *flags)
        assert result.returncode == 0, data
        images.append(out.read_bytes())
        with Image.open(out) as image:
            assert image.getpixel((0, 0))[3] == 255
    assert images[0] == images[1]
    assert images[0] != images[2]


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', 'bad', '1e309'])
def test_yaw_offset_rejects_nonfinite(value, tmp_path):
    out = tmp_path / 'invalid.png'
    result, data = run(MEDIA/'static-cube.glb', '--out', out, '--yaw-offset', value)
    assert result.returncode != 0 and data['ok'] is False
    assert '--yaw-offset must be finite' in data['error']
    assert not out.exists()


@pytest.mark.parametrize('offset', [90, 180, -90, 22.5, 450])
def test_yaw_offset_rotates_all_views(tmp_path, offset):
    # Neither bundled fixture is asymmetric from every angle. Build a real,
    # deliberately skewed tetrahedron so every tile can detect a yaw change.
    points = [(-0.8, 0, -0.4), (1.2, 0.1, -0.2), (-0.2, 0.3, 1.1), (0.3, 2, 0.2)]
    faces = [0, 2, 1, 0, 1, 3, 1, 2, 3, 2, 0, 3]
    vertices = [coordinate for index in faces for coordinate in points[index]]
    binary = struct.pack('<36f', *vertices)
    document = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
                'nodes': [{'mesh': 0}], 'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
                'buffers': [{'byteLength': len(binary)}],
                'bufferViews': [{'buffer': 0, 'byteLength': len(binary)}],
                'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 12, 'type': 'VEC3',
                               'min': [-0.8, 0, -0.4], 'max': [1.2, 2, 1.1]}]}
    encoded = json.dumps(document).encode()
    encoded += b' ' * (-len(encoded) % 4)
    source = tmp_path/'asymmetric.glb'
    source.write_bytes(struct.pack('<4sII', b'glTF', 2, 28 + len(encoded) + len(binary))
                       + struct.pack('<I4s', len(encoded), b'JSON') + encoded
                       + struct.pack('<I4s', len(binary), b'BIN\0') + binary)
    tiles = []
    for name, flags in [('default', []), ('zero', ['--yaw-offset', 0]),
                        ('offset', ['--yaw-offset', offset]), ('repeat', ['--yaw-offset', offset])]:
        out, split = tmp_path/f'{name}.png', tmp_path/name
        result, data = run(source, '--out', out, '--split-dir', split,
                           '--views', 6, '--shading', 'normals', '--tile-size', 128,
                           '--transparent', '--no-labels', '--chrome', CHROME, *flags)
        assert result.returncode == 0, data
        assert data['yaw_offset_deg'] == (offset if name in ('offset', 'repeat') else 0)
        assert data['views'] == NAMES
        tiles.append([Path(data['split_files'][view]).read_bytes() for view in NAMES])
    assert tiles[0] == tiles[1]
    assert tiles[2] == tiles[3]
    assert all(before != after for before, after in zip(tiles[0], tiles[2]))
    if offset in (90, 180, -90, 450):
        shift = (offset // 90) % 4
        assert tiles[2][:4] == tiles[0][shift:4] + tiles[0][:shift]


def test_harness_security_contract():
    source = SCRIPT.read_text()
    harness = (SCRIPT.parent/'render_harness.mjs').read_text()
    assert '--remote-debugging-pipe' in harness
    assert '--remote-debugging-port' not in harness + source
    assert 'about:blank' in harness and 'sha512-' in harness and '0.180.0' in harness
    assert 'blob:' in harness and 'setURLModifier' in source
