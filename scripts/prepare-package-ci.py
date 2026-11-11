#!/usr/bin/env python3
"""Apply only the verified Ath12k fetch compatibility fix to its pinned source.

Mesa/prelink validation and the reference, Cargo and Ninja input checks remain
enabled. No tree traversal, ignored patch failures, or file-existence reuse.
"""
import argparse
import ast
from pathlib import Path
import subprocess

UNIXNU = '97437dcf7389484a0eeaa8067725ce743aff18ef'
ATH12K = '48e23bf15fc21bbd30d5583b42b9c09ad65537db'
OLD = ('        subprocess.run(["git", "clone", "--depth", "1", "--branch", source["ref"],\n'
       '                        "--filter=blob:none", "--sparse", source["url"], str(directory)], check=True)')
NEW = '''        urls = [source["url"]]
        if "git.kernel.org" in source["url"]:
            urls.append(source["url"].replace("https://git.kernel.org/", "https://kernel.googlesource.com/"))
        for attempt in range(4):
            url = urls[attempt % len(urls)]
            try:
                import shutil as _shutil
                _shutil.rmtree(directory, ignore_errors=True)
                directory.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "init", "-q", str(directory)], check=True)
                subprocess.run(["git", "-C", str(directory), "sparse-checkout", "set", "--no-cone", *source["paths"]], check=True)
                subprocess.run(["git", "-C", str(directory), "fetch", "--depth", "1", "--filter=blob:none", url, source["commit"]], check=True)
                subprocess.run(["git", "-C", str(directory), "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
                break
            except Exception:
                if attempt == 3:
                    raise'''


def transform(source):
    if source.count(OLD) != 1 or source.count('"sparse-checkout", "add"') != 1:
        raise ValueError('Pinned Ath12k fetcher changed; review before adapting it')
    result = source.replace(OLD, NEW).replace('"sparse-checkout", "add"', '"sparse-checkout", "set", "--no-cone"')
    ast.parse(result)
    return result


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unixnu', required=True, type=Path)
    args = parser.parse_args()
    device = Path(__file__).resolve().parents[1]
    ath = device / 'drivers/Ath12kWifi'
    for path, expected in ((args.unixnu, UNIXNU), (ath, ATH12K)):
        if git(path, 'rev-parse', 'HEAD') != expected:
            raise SystemExit(f'Unexpected source revision: {path}')
    original = subprocess.check_output(['git', '-C', str(ath), 'show', 'HEAD:tools/fetch-sources.py'], text=True)
    fixed = transform(original)
    path = ath / 'tools/fetch-sources.py'
    current = path.read_text()
    if current not in (original, fixed):
        raise SystemExit('Ath12k fetcher has unreviewed local modifications')
    if current != fixed:
        path.write_text(fixed)
    print('Prepared pinned Ath12k fetcher; Mesa, prelink and build input checks remain enabled')


if __name__ == '__main__':
    main()
