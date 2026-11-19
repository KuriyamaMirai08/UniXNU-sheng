#!/usr/bin/env python3
"""Check the production UFS header without suppressing unused-function errors.

This is a host header regression, not an XNU/IOKit target compilation. The
four optional helpers stay unreferenced, as they do in NativeUfs.cpp. Restore
each original declaration to prove that the diagnostic is still enabled.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


REPO = Path(__file__).resolve().parents[2]
OPTIONAL = {
    'ufsWriteAuthorityHasPlatformLock': 'bool',
    'ufsWriteAuthoritySetProbe': 'void',
    'ufsWriteAuthorityAllows': 'bool',
    'ufsWriteAuthorityInflight': 'uint64_t',
}

def sdk_flags():
    """Resolve the real macOS SDK so the C/C++ standard headers are found.

    UfsWriteAuthority.h has no includes of its own: it relies on its consumer
    for <stdint.h>/<string.h>, the headers NativeUfs.cpp brings in first. The
    strict diagnostic run must therefore compile with the active SDK instead of
    bare Apple clang, which ships no libc or libc++ headers by itself.
    """
    try:
        sdk = subprocess.run(['xcrun', '--sdk', 'macosx', '--show-sdk-path'],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    path = sdk.stdout.strip()
    if sdk.returncode or not path or not Path(path).is_dir():
        return []
    flags = ['-isysroot', path]
    cxx = Path(path) / 'usr/include/c++/v1'
    if cxx.is_dir():
        flags += ['-isystem', str(cxx)]
    return flags

# Direct consumers in the reviewed NativeUfs.cpp and RootCommands.h. Taking
# their addresses marks those entry points used without calling fake hardware.
# Deliberately omit OPTIONAL so its original static declarations fail.
CONSUMERS = (
    'ufsWriteAuthoritySetLock',
    'ufsWriteAuthorityTryAcquire',
    'ufsWriteAuthorityAcquire',
    'ufsWriteAuthorityRelease',
    'ufsAuthorityProbe',
    'ufsWriteAuthorityBaseValid',
    'ufsWriteAuthorityReset',
    'ufsWriteAuthorityRevoke',
    'ufsWriteAuthorityEstablish',
    'ufsWriteAuthorityRegister',
    'ufsWriteAuthorityRegisterPair',
    'ufsWriteAuthorityRoleWindowLocked',
    'ufsWriteAuthorityRoleWindow',
    'ufsWriteAuthorityAllowsLocked',
    'ufsWriteAuthorityEnterInflightLocked',
    'ufsWriteAuthorityExitInflightLocked',
    'ufsWriteAuthorityExitInflight',
    'ufsWriteAuthoritySnapshot',
    'ufsWriteAuthorityEpoch',
    'ufsWriteAuthorityState',
    'ufsWriteAuthorityNoteDenied',
)


def restored_declaration(text, name):
    declaration = 'static inline ' + OPTIONAL[name] + ' ' + name + ' ('
    if text.count(declaration) != 1:
        raise RuntimeError('Missing or duplicate reviewed declaration: ' + name)
    return text.replace(declaration, declaration.replace('static inline ', 'static '), 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default=shutil.which('clang++'))
    parser.add_argument('--header', type=Path)
    args = parser.parse_args()
    if not args.compiler:
        parser.error('Pass the actual clang compiler path')
    version = subprocess.run([args.compiler, '--version'], capture_output=True,
                             text=True, check=True).stdout
    print(version, end='')
    standards = sdk_flags()
    print(json.dumps(dict(case='sdk_probe', compiler=args.compiler, flags=standards)))

    with tempfile.TemporaryDirectory(prefix='stage0c1b-authority-') as directory:
        scratch = Path(directory)
        if args.header is not None:
            header_text = args.header.read_text(encoding='utf-8-sig')
        else:
            # UfsWriteAuthority.h is a new file in the reviewed component patch.
            # Apply that exact production file instead of a hand-written model.
            subprocess.run(['git', 'init', '-q', str(scratch)], check=True)
            subprocess.run(['git', '-C', str(scratch), 'apply',
                            '--include=UfsWriteAuthority.h',
                            str(REPO / 'stage0c1b/patches/shenguFs.patch')], check=True)
            header_text = (scratch / 'UfsWriteAuthority.h').read_text(encoding='utf-8')

        source = scratch / 'consumers.cpp'
        source.write_text('#include <stdint.h>\n#include <string.h>\n'
                          '#include "UfsWriteAuthority.h"\n'
                          'void stage0c1b_authority_consumers ()\n{\n' +
                          ''.join('  (void)&' + name + ';\n' for name in CONSUMERS) +
                          '}\n', encoding='utf-8')

        def compile_case(name, contents, expected):
            (scratch / 'UfsWriteAuthority.h').write_text(contents, encoding='utf-8')
            command = [args.compiler, '-x', 'c++', '-std=gnu++2b',
                       '-Wall', '-Wextra', '-Werror', '-Wunused-function',
                       *standards, '-fsyntax-only', str(source)]
            result = subprocess.run(command, capture_output=True, text=True)
            output = result.stdout + result.stderr
            found = {helper for helper in OPTIONAL
                     if "unused function '" + helper + "'" in output}
            errors = sum(': error:' in line for line in output.splitlines())
            passed = ((result.returncode == 0 and not output.strip()) if not expected
                      else result.returncode != 0 and found == set(expected) and
                      errors == len(expected) and '[-Werror,-Wunused-function]' in output)
            print(json.dumps(dict(case=name, command=command, returncode=result.returncode,
                                  unused_helpers=sorted(found), errors=errors, passed=passed)))
            if output:
                print(output, end='' if output.endswith('\n') else '\n')
            if not passed:
                raise RuntimeError('Strict header regression failed: ' + name)

        original = header_text
        for helper in OPTIONAL:
            original = restored_declaration(original, helper)
        compile_case('original_four_static_declarations', original, tuple(OPTIONAL))
        compile_case('fixed_production_header', header_text, ())
        for helper in OPTIONAL:
            compile_case('restore_' + helper,
                         restored_declaration(header_text, helper), (helper,))
        print('PASS: 6 strict production-header cases; unused-function diagnostics remain enabled')


if __name__ == '__main__':
    main()
