"""Build independent source ZIPs and SHA256 manifests; excludes runtime data."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'packages'


def sources(folder):
    for p in sorted(folder.rglob('*')):
        relative = p.relative_to(folder)
        if not p.is_file() or any(x in relative.parts for x in ('__pycache__', '.git', 'run-data', 'instances', 'runtime', 'crm-browser-profile')):
            continue
        if p.suffix in ('.pyc', '.log', '.lock') or p.name.endswith('.local.json'):
            continue
        if p.name in ('release-manifest.json', 'dashboard-config.json', 'dashboard-config.backup.json', 'share-config.json', 'status.json') or p.name.endswith('-status.json'):
            continue
        yield p


def main():
    PACKAGES.mkdir(exist_ok=True)
    sums = {}
    for name, identity, port in [('main-dashboard', 'main', 8765), ('replica-dashboard', 'replica', 8766)]:
        folder = ROOT / name
        files = list(sources(folder))
        connector = json.loads((folder / 'chrome-extension/manifest.json').read_text(encoding='utf-8-sig'))['version']
        manifest = {'version': '2026.11.13-workdesk', 'instance': identity, 'port': port, 'connectorVersion': connector,
                    'files': [{'path': p.relative_to(folder).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
        target = folder / 'release-manifest.json'
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        archive = PACKAGES / f'{name}.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in files + [target]:
                info = zipfile.ZipInfo(f'{name}/{p.relative_to(folder).as_posix()}', (2026, 11, 13, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(info, p.read_bytes())
        sums[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
        print(name, len(files), 'files', archive.stat().st_size, 'bytes')
    (PACKAGES / 'SHA256SUMS.json').write_text(json.dumps(sums, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
