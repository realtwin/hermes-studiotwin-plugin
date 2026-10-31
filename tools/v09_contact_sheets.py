"""Build contact sheets only from verified production-bundle captures."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / 'evidence' / 'v08'
manifest = json.loads((ROOT / 'visual-manifest.json').read_text())
order = ['3d-model', 'animation-rigged', 'audio-sfx', 'env-360-stickers',
         'pbr-material', 'image-concept-compare', 'video-player', 'task-progress-queued',
         'task-progress-running', 'task-progress-card', 'workspace-library', 'workspace-jobs',
         'workspace-concepts', 'workspace-upload', 'webgl-pool-six']
expected = {f'{name}-{theme}.png' for name in order for theme in ('dark', 'light')}
actual = {r['file'] for r in manifest['captures']}
assert len(manifest['captures']) == 30 and actual == expected
assert {p.name for p in (ROOT / 'screenshots').glob('*.png')} == expected
for theme in ('dark', 'light'):
    for batch in range(4):
        sheet = Image.new('RGB', (1440, 1200), '#888888')
        draw = ImageDraw.Draw(sheet)
        for slot, name in enumerate(order[batch * 4:batch * 4 + 4]):
            filename = f'{name}-{theme}.png'
            with Image.open(ROOT / 'screenshots' / filename) as original:
                image = original.convert('RGB')
                image.thumbnail((710, 550))
            x, y = (slot % 2) * 720, (slot // 2) * 600
            draw.text((x + 8, y + 8), filename, fill='#111111')
            sheet.paste(image, (x, y + 30))
        sheet.save(ROOT / f'contact-{theme}-{batch + 1}.jpg', quality=92)
print(json.dumps({'captures': len(actual), 'contact_sheets': 8,
                  'errors': manifest['errors'], 'consoleErrors': manifest['consoleErrors'],
                  'overflow': [r['file'] for r in manifest['captures'] if r['scroll'] > r['width']]}))
