"""Exact transforms for the fixed framework, applied only to the experiment copy."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

def transform(name, source):
    if name=='scripts/unixnu/patches.py':
        old='            except Error as error:\n                shutil.rmtree(work)\n'
        new='            except Error as error:\n                # REPRO: retain the failed patch tree for evidence.\n'
    elif name=='scripts/unixnu/kernel.py':
        old='        except Error:\n            if not record.is_file():\n                raise\n'
        new='        except Error:\n            # REPRO: stop even when bootstrap left a startup record.\n            raise\n'
        if source.count(old)!=1: raise ValueError('bootstrap marker mismatch')
        source=source.replace(old,new)
        old="    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.prelink-') as directory:\n"
        new="    with contextlib.nullcontext(tempfile.mkdtemp(dir=output.parent, prefix='.prelink-')) as directory:\n"
        source='import contextlib\n'+source
    else: raise ValueError(name)
    if source.count(old)!=1: raise ValueError('preservation marker mismatch: '+name)
    result=source.replace(old,new)
    ast.parse(result)
    return result

def apply(root,evidence):
    records=[]
    for name in ['scripts/unixnu/patches.py','scripts/unixnu/kernel.py']:
        path=Path(root)/name
        before=path.read_bytes()
        after=transform(name,before.decode()).encode()
        (Path(evidence)/(Path(name).stem+'.preservation.patch')).write_text(''.join(difflib.unified_diff(
            before.decode().splitlines(True),after.decode().splitlines(True),fromfile='a/'+name,tofile='b/'+name)))
        path.write_bytes(after)
        records.append(dict(path=name,before=hashlib.sha256(before).hexdigest(),after=hashlib.sha256(after).hexdigest()))
    (Path(evidence)/'preservation-transforms.json').write_text(json.dumps(records,indent=2))
