"""Read preserved inputs and observe the original Layout without changing it."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('inputs', type=Path)
p.add_argument('contract', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
root = a.inputs
contract = json.loads(a.contract.read_text())
kit = root / 'UniXNU/kits/XnuPrelink'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
for name, digest in contract['engine'].items():
    assert sha(kit / name) == digest, name
sys.path.insert(0, str(kit))
from kc_image import Image
from fileset_emit import dependency_closure, rebase_collection
from fileset_layout import Layout, align

board = root / 'out/sheng/ipados-27.0.1-24A446/sheng_ipados27'
native_path = board / 'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
old_path = root / 'baseline-evidence/native.macho'
cache_path = root / 'out/ipsw/24A446/kernelcache.decompressed'
assert sha(native_path) == 'e2d5224f975acc40c8dcad03111aca23fde00599e0ae39902c94df5f11a712aa'
assert sha(old_path) == contract['inputs']['native']
assert sha(cache_path) == contract['inputs']['kernelcache']
raw = cache_path.read_bytes()
closure = dependency_closure(Image(raw), contract['roots'])
early = {k:int(v,16) for k,v in contract['early_security_init'].items()}

def measure(path):
    native = Image(path.read_bytes())
    cache, slide, _ = rebase_collection(Image(raw), native.base, closure, early, set(contract['roots']))
    error = None
    try:
        layout = Layout(cache, native, closure)
    except ValueError as ex:
        error = str(ex)
        tb = ex.__traceback__
        while tb.tb_next:
            tb = tb.tb_next
        assert tb.tb_frame.f_code.co_filename == str(kit / 'fileset_layout.py')
        layout = tb.tb_frame.f_locals['self']
    spans = []
    for owner, (_, offset) in cache.entries.items():
        if owner == 'com.apple.kernel' or owner not in closure:
            continue
        for segment in Image(cache.data, offset).segments:
            if segment['size'] and segment['name'] != '__LINKEDIT':
                spans.append(dict(owner=owner, segment=segment['name'], begin=segment['va'], end=segment['va']+segment['size']))
    code = next(s for s in cache.segments if s['name']=='__TEXT_EXEC')
    kept = [s for s in spans if code['va'] <= s['begin'] < code['va']+code['size']]
    end_kept = max([code['va']]+[s['end'] for s in kept])
    text = next(s for s in native.segments if s['name']=='__TEXT_EXEC')
    kld = next(s for s in native.segments if s['name']=='__KLD')
    start = align(end_kept)
    code_end = align(start+text['size']) + kld['size']
    data_va = next(s for s in cache.segments if s['name']=='__DATA')['va']
    assert layout.placements['__TEXT_EXEC']==start
    assert layout.end('__KLD')==code_end
    return dict(sha256=sha(path), bytes=path.stat().st_size, native_base=hex(native.base), collection_slide=slide,
                layout_error=error, end_kept=hex(end_kept), native_text_start=hex(start),
                text_vmsize=text['size'], text_filesize=text['filesize'], kld_vmsize=kld['size'],
                code_end=hex(code_end), collection_data_va=hex(data_va), overflow_bytes=code_end-data_va,
                final_retained_span=[s for s in kept if s['end']==end_kept],
                retained_executable_root_spans=kept,
                native_segments=[{k:s[k] for k in ('name','va','size','fileoff','filesize')} for s in native.segments]), native

new, ni = measure(native_path)
old, oi = measure(old_path)
ns = {s['name']:s for s in ni.segments}
os = {s['name']:s for s in oi.segments}
delta = {name:{key:ns[name][key]-os[name][key] for key in ('size','filesize')} for name in ns if name in os}

def functions(image):
    starts = image.function_starts()
    names = image.symbols()
    result = {}
    for begin, end in zip(starts, starts[1:]):
        for name in names.get(begin, ()):
            result[name] = end-begin
    return result

nf, of = functions(ni), functions(oi)
growth = sorted((dict(name=n, old_size=of.get(n,0), new_size=size, delta=size-of.get(n,0)) for n,size in nf.items() if size>of.get(n,0)), key=lambda row:row['delta'], reverse=True)
report = dict(original_engine_verified=True, original_layout_modified=False, device_operations=0,
              closure=sorted(closure), new=new, old=old, segment_deltas=delta,
              largest_named_function_growth=growth[:100],
              function_size_limit='Function-start intervals include padding; aliases may share intervals. This is attribution evidence, not an additive code-size accounting.')
a.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({label:{k:v for k,v in row.items() if k not in ('retained_executable_root_spans','native_segments')} for label,row in [('new',new),('old',old)]},indent=2))
