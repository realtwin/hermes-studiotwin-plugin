"""V07 no-spend admission probe. Use a disposable test interpreter with the
reference Hermes checkout on PYTHONPATH; never install into a daily profile.
"""
from pathlib import Path
import json
import subprocess
import tempfile
from hermes_cli.agent_plugins import load_agent_plugin
from hermes_cli.plugin_validate import validate_plugin_dir

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / '.verification'
OUTPUT.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=OUTPUT) as temp:
    package = load_agent_plugin(ROOT, Path(temp) / 'data')
    report = validate_plugin_dir(ROOT)
    value = report.to_dict()
    value['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    value['skills'] = [{'name': s.name, 'file': str(s.skill_md), 'version': s.frontmatter.get('version')} for s in package.skills]
    value['desktop_bundle_exists'] = (ROOT / 'desktop/plugin.js').is_file()
    print(json.dumps(value, indent=2))
    (OUTPUT / 'host-validation.json').write_text(json.dumps(value, indent=2) + '\n')
    assert report.ok and value['warnings'] == [], value
    assert package.diagnostics == (), package.diagnostics
    assert len(package.skills) == 1 and package.skills[0].name == 'studiotwin'
    assert package.skills[0].frontmatter['version'] == '0.2.0'
    assert value['desktop_bundle_exists']
