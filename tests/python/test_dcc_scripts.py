"""Offline DCC contracts. Blender integration is explicitly optional, pure preflight is not."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'skills/studiotwin/scripts'
MEDIA = ROOT / 'tests/fixtures/media'


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(script, *args):
    exe = 'node' if script.endswith('.mjs') else sys.executable
    return subprocess.run([exe, str(SCRIPTS/script), *map(str,args)], capture_output=True, text=True, timeout=45)


@pytest.mark.parametrize('name,counts', [
    ('static-cube.glb', {'triangles':12,'vertices':8,'meshes':1,'primitives':1,'textures':0,'skins':0,'joints':0,'skinned_mesh_nodes':0,'clips':[]}),
    ('rigged-animated.glb', {'triangles':16,'vertices':12,'meshes':1,'primitives':1,'textures':0,'skins':1,'joints':2,'skinned_mesh_nodes':1,'clips':['Wave','Idle']}),
])
def test_stats_exact(name, counts):
    path = MEDIA/'model'/name
    r = run('glb_stats.py',path)
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data == {**counts,'path':str(path),'bytes':path.stat().st_size}


def test_stats_errors_per_file(tmp_path):
    bad = tmp_path/'bad.glb'
    bad.write_bytes(b'not a GLB')
    r = run('glb_stats.py',bad,MEDIA/'model/static-cube.glb')
    rows = list(map(json.loads,r.stdout.splitlines()))
    assert r.returncode == 1
    assert 'error' in rows[0] and rows[1]['triangles'] == 12
    corrupt = bytearray((MEDIA/'model/static-cube.glb').read_bytes())
    corrupt[4:8] = (99).to_bytes(4,'little')
    bad.write_bytes(corrupt)
    assert 'error' in json.loads(run('glb_stats.py',bad).stdout)


def test_blender_helpers():
    b = load('blender_handoff')
    assert b.parse_lods('0.5,0.25') == [0.5,0.25]
    for value in ['1','0','nan','inf','0.1,0.8','bad']:
        with pytest.raises(b.HandoffRefused):
            b.parse_lods(value)


@pytest.mark.parametrize('flags', [[], ['--tris','-1'], ['--max-texture','-1'], ['--export','invalid'], ['--lods','nan']])
def test_blender_invalid_arguments_without_blender(flags):
    r = run('blender_handoff.py',*flags)
    assert r.returncode != 0
    assert 'Traceback' not in r.stderr


def test_blender_source_protection_and_no_clobber(tmp_path):
    src = tmp_path/'model_optimized.glb'
    src.write_bytes((MEDIA/'model/static-cube.glb').read_bytes())
    original = src.read_bytes()
    for flags in [[], ['--force']]:
        r=run('blender_handoff.py','--input',src,'--out-dir',tmp_path,*flags)
        assert r.returncode != 0 and 'source file' in r.stdout
        assert src.read_bytes() == original
    alias = tmp_path/'other_optimized.glb'; os.link(src,alias)
    r=run('blender_handoff.py','--input',src,'--out-dir',tmp_path,'--name','other','--force')
    assert r.returncode != 0 and 'source file' in r.stdout
    r=run('blender_handoff.py','--render',src,'--png',src,'--force')
    assert r.returncode != 0 and 'source file' in r.stdout
    assert src.read_bytes() == original


def test_blender_publish_no_clobber(tmp_path):
    b=load('blender_handoff'); source=tmp_path/'stage'; target=tmp_path/'out'
    source.write_bytes(b'new'); target.write_bytes(b'old')
    with pytest.raises(FileExistsError): b.publish(str(source),str(target),False)
    assert target.read_bytes()==b'old'


@pytest.mark.skipif(os.environ.get('STUDIOTWIN_BLENDER_TEST') != '1', reason='opt-in real Blender CPU render')
def test_real_cpu_render(tmp_path):
    source = MEDIA/'model/rigged-animated.glb'
    original = source.read_bytes()
    dest = tmp_path/'preview.png'
    r = run('blender_handoff.py','--render',source,'--png',dest)
    assert r.returncode == 0, r.stdout+r.stderr
    assert 'HANDOFF_RENDER ' in r.stdout
    assert dest.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    assert source.read_bytes() == original
    again = run('blender_handoff.py','--render',source,'--png',dest)
    assert again.returncode != 0 and 'output exists' in again.stdout


def test_preview_help_and_list():
    r=run('render_preview.mjs','--help'); assert r.returncode==0 and '--list-clips' in r.stdout
    r=run('render_preview.mjs',MEDIA/'model/rigged-animated.glb','--list-clips')
    assert r.returncode==0,r.stdout+r.stderr
    assert json.loads(r.stdout)=={'ok':True,'clips':[{'name':'Wave','duration':1},{'name':'Idle','duration':1}]}
    r=run('render_preview.mjs',MEDIA/'model/static-cube.glb','--list-clips')
    assert json.loads(r.stdout)['clips']==[]


@pytest.mark.parametrize('flags', [['--fps','NaN'], ['--fps','0'], ['--size','100'], ['--seconds','Infinity'], ['--max-mb','-1'], ['--out','x.glb'], ['--unknown']])
def test_preview_validation(flags):
    r=run('render_preview.mjs',MEDIA/'model/static-cube.glb',*flags)
    assert r.returncode!=0
    assert json.loads(r.stdout)['ok'] is False
    assert len(r.stdout.splitlines())==1


def test_preview_refuses_existing_output(tmp_path):
    dest=tmp_path/'out.mp4';dest.write_bytes(b'original')
    r=run('render_preview.mjs',MEDIA/'model/static-cube.glb','--out',dest)
    assert r.returncode!=0 and 'exists' in r.stdout
    assert dest.read_bytes()==b'original'
