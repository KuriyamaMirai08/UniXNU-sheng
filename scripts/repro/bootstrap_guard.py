"""Accept only the observed bootstrap missing-archive failure, never final link errors."""
import hashlib
import json
import re
from pathlib import Path

EXPECTED = frozenset('''_boot_cache_input_capture _boot_log_rounds _corecrypto_kext_start
_native_legacy_display_late_probe _native_legacy_display_probe _native_ram_block_gpu_addon
_native_ram_block_volume_seed _native_source_storage_start _native_verified_block_manifest_sha384
_native_verified_block_root_authorized _native_verified_block_volume_device _sheng_boot_watchdog_policy'''.split())

def classify(text, expected=EXPECTED):
    marker='Undefined symbols for architecture arm64e.kernel:'
    if text.count(marker)!=1: raise ValueError('Expected exactly one arm64e.kernel undefined-symbol block')
    before,block=text.split(marker)
    if re.search(r'(?:fatal error:|error:|\*\*\*)',before): raise ValueError('Earlier compile/tool error')
    ld=list(re.finditer(r'^\s*LD mach\.development\.bcm2837\.unstripped\.noctf\s*$',before,re.M))
    if len(ld)!=1:
        raise ValueError('Failure is not the expected native LD')
    for line in before[ld[0].end():].splitlines():
        if line.strip() and not re.fullmatch(r"ld: warning: search path '.*/\.cache/fakeroot/usr/local/lib/kernel/platform' not found",line):
            raise ValueError('Unexpected operation between LD and undefined symbols')
    names=set(re.findall(r'^\s+"(_[^"]+)", referenced from:',block,re.M))
    if names!=expected: raise ValueError('Bootstrap symbol set changed: '+repr(sorted(names^expected)))
    errors=[line.strip() for line in block.splitlines() if re.search(r'(?:fatal error:|error:|\*\*\*)',line)]
    for line in errors:
        if line=='clang++: error: linker command failed with exit code 1 (use -v to see invocation)': continue
        if re.match(r'^make(?:\[\d+\])?: \*\*\* \[.*\] Error [12]$',line): continue
        raise ValueError('Unexpected error after LD: '+line)
    if 'ld: symbol(s) not found for architecture arm64e.kernel' not in block or not errors:
        raise ValueError('Missing linker failure evidence')
    return sorted(names)

def accept_bootstrap_failure(ctx, env, started):
    report={'accepted':False,'started':started}
    destination=ctx.logs/'bootstrap-guard.json'
    try:
        if env.get('XNU_BOOTSTRAP')!='1': raise ValueError('Not bootstrap')
        log=ctx.logs/'kernel-bootstrap.log'
        data=log.read_bytes(); report['log_sha256']=hashlib.sha256(data).hexdigest()
        expected = EXPECTED
        if env.get('UNIXNU_SHENG_BOOT_CANDIDATE') == '1':
            if env.get('UNIXNU_IPSW_BUILD') != '24A446':
                raise ValueError('Candidate bootstrap guard selected for a different OS')
            expected = EXPECTED | {'_sheng_image4_normal_pal'}
        report['symbols']=classify(data.decode(errors='replace'), expected)
        obj=ctx.tree/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
        startup=obj/'osfmk/DEVELOPMENT/startup.o.json'
        record=json.loads(startup.read_text().strip().rstrip(','))
        if '-c' not in record['arguments'] or 'arm64e' not in record['arguments']:
            raise ValueError('Unexpected startup compile record')
        lists=list(obj.rglob('link.filelist'))
        if len(lists)!=1: raise ValueError('Missing or ambiguous link.filelist')
        paths=[Path(x.strip()) for x in lists[0].read_text().splitlines() if x.strip()]
        if not paths: raise ValueError('Empty link.filelist')
        for p in [startup,lists[0],*paths]:
            if not p.resolve().is_relative_to(obj.resolve()) or not p.is_file() or not p.stat().st_size:
                raise ValueError('Missing/invalid bootstrap input: '+str(p))
            if p.stat().st_mtime < started-2: raise ValueError('Bootstrap input predates this pass: '+str(p))
        report.update(accepted=True,status='expected-bootstrap-link-failure',link_objects=len(paths))
    except Exception as exc:
        report['reason']=repr(exc)
    destination.write_text(json.dumps(report,indent=2)+'\n')
    print('REPRO bootstrap guard: '+json.dumps(report),flush=True)
    return report['accepted']
