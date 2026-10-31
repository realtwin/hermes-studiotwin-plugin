"""Real anonymous-pipe Chrome multiview contracts; no paid services."""
import json
import os
from pathlib import Path
import shutil
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
    assert set(data) == {'ok', 'sheet', 'views', 'split_files', 'shading', 'width', 'height', 'bytes'}
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


def test_harness_security_contract():
    source = SCRIPT.read_text()
    harness = (SCRIPT.parent/'render_harness.mjs').read_text()
    assert '--remote-debugging-pipe' in harness
    assert '--remote-debugging-port' not in harness + source
    assert 'about:blank' in harness and 'sha512-' in harness and '0.180.0' in harness
    assert 'blob:' in harness and 'setURLModifier' in source
