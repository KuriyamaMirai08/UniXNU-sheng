import json
import pathlib
import subprocess
import sys
import tempfile
import tomllib

SOURCE = pathlib.Path(__file__).resolve().parents[1]
yaml = (SOURCE / '.github/workflows/package.yml').read_text()
guard = yaml.split('<<\'PY\'\n', 1)[1].split('\n          PY', 1)[0]
guard = '\n'.join(line[10:] for line in guard.splitlines())
compile(guard, '<workflow-checkout-guard>', 'exec')
original = (SOURCE / 'unixnu.lock').read_text()
pins = json.loads((SOURCE / 'reports/ipados26-source-drivers.json').read_text())['source_pins']
values = tomllib.loads(original)['source']
for name in ('IOHIDFamily', 'IOStorageFamily'):
    values[name] = {'commit': pins[name]['commit']}
lines = [original.splitlines()[0]]
for name in sorted(values):
    lines.extend(['', f'[source."{name}"]', f'commit = "{values[name]["commit"]}"'])
resolved = '\n'.join(lines) + '\n'

def git(repo, *args, check=True):
    return subprocess.run(['git', '-C', str(repo), *args], check=check,
                          capture_output=True, text=True)

def validate(repo, code=guard):
    result = subprocess.run([sys.executable, '-', str(repo)], input=code,
                            capture_output=True, text=True)
    if result.returncode:
        return False
    return git(repo, 'diff', '--exit-code', '--ignore-submodules=dirty', 'HEAD', '--',
               '.', ':(top,exclude)unixnu.lock', check=False).returncode == 0

with tempfile.TemporaryDirectory() as folder:
    repo = pathlib.Path(folder)
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'Fixture')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    git(repo, 'config', 'core.autocrlf', 'false')
    (repo / 'scripts').mkdir()
    (repo / 'scripts/prepare-package-ci.py').write_bytes((SOURCE / 'scripts/prepare-package-ci.py').read_bytes())
    (repo / 'unixnu.lock').write_text(original, newline='\n')
    (repo / 'source.txt').write_text('reviewed\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'fixture baseline')
    base = git(repo, 'rev-parse', 'HEAD').stdout.strip()
    assert validate(repo), 'clean lock rejected'
    (repo / 'unixnu.lock').write_text(resolved, newline='\n')
    blob = git(repo, 'hash-object', 'unixnu.lock').stdout.strip()
    assert blob.startswith('36c2b18'), blob
    old_diff = git(repo, 'diff', '--exit-code', '--ignore-submodules=dirty', 'HEAD', '--', check=False)
    assert old_diff.returncode == 1, 'original failure not reproduced'
    assert validate(repo), 'observed lock rejected'
    for bad in (resolved.replace(pins['IOStorageFamily']['commit'], '0' * 40),
                resolved.replace(values['xnu']['commit'], '1' * 40),
                resolved + '\n[source."unknown"]\ncommit = "' + '2' * 40 + '"\n'):
        (repo / 'unixnu.lock').write_text(bad, newline='\n')
        assert not validate(repo), 'unknown lock change accepted'
    (repo / 'unixnu.lock').unlink()
    assert not validate(repo), 'missing lock accepted'
    (repo / 'unixnu.lock').write_text(resolved, newline='\n')
    git(repo, 'add', 'unixnu.lock')
    assert not validate(repo), 'staged lock accepted'
    git(repo, 'restore', '--staged', 'unixnu.lock')
    (repo / 'source.txt').write_text('unknown edit\n')
    assert not validate(repo), 'other tracked edit accepted'
    (repo / 'source.txt').write_text('reviewed\n')
    # Check a real branch transition with retained lock and cache/private sentinels.
    (repo / 'workflow.txt').write_text(yaml)
    git(repo, 'add', 'workflow.txt')
    git(repo, 'commit', '-qm', 'fixture workflow fix')
    target = git(repo, 'rev-parse', 'HEAD').stdout.strip()
    git(repo, 'checkout', '--detach', base)
    sentinels = [repo / '.cache/object.o', repo / 'out/tree/build/object.o', repo / 'private/inputs/data.dbr']
    for path in sentinels:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture-preserve-only')
    snapshots = [(p.read_bytes(), p.stat().st_mtime_ns) for p in sentinels]
    assert validate(repo)
    git(repo, 'checkout', '--detach', target)
    assert (repo / 'unixnu.lock').read_text() == resolved
    assert snapshots == [(p.read_bytes(), p.stat().st_mtime_ns) for p in sentinels]
    print('PASS: reproduced #65 lock blob ' + blob)
    print('PASS: clean/observed locks accepted; wrong family/other pin/extra entry/missing/staged lock and other source edits rejected')
    print('PASS: real checkout preserves retained lock and cache/private fixture bytes and timestamps')
