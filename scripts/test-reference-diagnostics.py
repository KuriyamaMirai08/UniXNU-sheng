"""Exercise the actual reference binary and refuse damaged provider definitions."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import tempfile

from reference_diagnostics import verify_diagnostic_providers

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--binary', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
data = args.binary.read_bytes()
positive = verify_diagnostic_providers(args.binary)
cases = [('truncated', data[:31])]
for name, row in positive.items():
    body = bytearray(data)
    body[row['file_offset'] + (2 if name == '_mach_assert_jump_key' else 4)] ^= 1
    cases.append((name + ' damaged body', body))
# Hiding a name in an undefined or debug entry cannot satisfy N_SECT checks.
at = 32
for _ in range(struct.unpack_from('<I', data, 16)[0]):
    kind, size = struct.unpack_from('<II', data, at)
    if kind == 2:
        symoff, count, strings, _ = struct.unpack_from('<4I', data, at + 8)
        break
    at += size
body = bytearray(data)
for i in range(count):
    pos = symoff + i * 16
    index, kind = struct.unpack_from('<IB', data, pos)
    name = data[strings + index:data.index(b'\0', strings + index)].decode()
    if name in positive and not kind & 0xe0 and kind & 0x0e == 0x0e:
        body[pos + 4] = 1  # N_UNDF | N_EXT, same name and old address.
cases.append(('undefined names with stale values', body))
negatives = []
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'reference.macho'
    for name, content in cases:
        path.write_bytes(content)
        try:
            verify_diagnostic_providers(path)
        except ValueError as error:
            negatives.append(dict(case=name, refused=True, error=str(error)))
        else:
            raise AssertionError('Accepted damaged provider: ' + name)
record = dict(binary_sha256=hashlib.sha256(data).hexdigest(), positive=positive, negative=negatives,
              actual_retained_binary=True, production_binary_modified=False)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(dict(real_providers=len(positive), negative_cases_refused=len(negatives))))
