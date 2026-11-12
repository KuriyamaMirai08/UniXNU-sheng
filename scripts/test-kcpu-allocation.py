"""Compile the real allocation helper and test failure, zeroing and reuse."""
from pathlib import Path
import subprocess
import struct
import sys
import tempfile

device = Path(__file__).resolve().parents[1]
source = (device / 'package/BootUiTraceProbe.c').read_text()
begin = source.index('struct bt_kcpu_seen {')
end = source.index('void boot_kcpu_scan(', begin)
helper = source[begin:end]
prefix = '''
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#define BT_KCPU_SEEN 1024
static unsigned calls;
static bool fail=true;
static void *IOMallocAligned(size_t size, size_t alignment) {
 ++calls;assert(size==16384 && alignment==4096);
 if(fail)return NULL;
 void *p=malloc(size);assert(p);memset(p,0xa5,size);return p;
}
'''
main = '''
int main(void) {
 assert(!prepare_kcpu_seen() && !kcpu_seen && calls==1);
 fail=false;assert(prepare_kcpu_seen() && kcpu_seen && calls==2);
 for(unsigned i=0;i<BT_KCPU_SEEN;++i)assert(!kcpu_seen[i].tid && !kcpu_seen[i].time);
 kcpu_seen[1023].tid=55;kcpu_seen[1023].time=99;
 assert(prepare_kcpu_seen() && calls==2 && kcpu_seen[1023].tid==55 && kcpu_seen[1023].time==99);
 free(kcpu_seen);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='kcpu-host-') as temporary:
    root = Path(temporary)
    (root / 'test.c').write_text(prefix + helper + main)
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
    if sys.platform == 'darwin':
        header = '#include <stdint.h>\n#include <stdbool.h>\n#include <stddef.h>\n#include <string.h>\n#define BT_KCPU_SEEN 1024\nvoid *IOMallocAligned(size_t,size_t);\n'
        versions = {'before': 'static struct {uint64_t tid,time;} kcpu_seen[1024];\nvoid *exercise(void){return kcpu_seen;}\n',
                    'after': helper + '\nvoid *exercise(void){prepare_kcpu_seen();return kcpu_seen;}\n'}
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
        sizes = {}
        for mode, body in versions.items():
            path = root / (mode + '.c')
            path.write_text(header + body)
            obj = root / (mode + '.o')
            subprocess.run(['xcrun', 'clang', '-target', 'arm64e-apple-ios27.0', '-isysroot', sdk,
                            '-mkernel', '-c', str(path), '-o', str(obj)], check=True)
            blob = obj.read_bytes()
            commands, = struct.unpack_from('<I', blob, 16)
            at, sizes[mode] = 32, 0
            for _ in range(commands):
                command, length = struct.unpack_from('<II', blob, at)
                if command == 0x19:
                    count, = struct.unpack_from('<I', blob, at + 64)
                    for index in range(count):
                        section = at + 72 + index * 80
                        name = blob[section:section + 16].split(b'\0')[0]
                        if name in (b'__bss', b'__common'):
                            size, = struct.unpack_from('<Q', blob, section + 40)
                            sizes[mode] += size
                at += length
        assert sizes == {'before': 16384, 'after': 8}, sizes
        print('PASS: real arm64e object zero-fill bytes:', sizes)
print('PASS: real kcpu allocation helper: failure, zero initialization, all 1024 slots and one-time reuse')
