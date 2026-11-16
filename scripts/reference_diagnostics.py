"""Qualify real defined diagnostic providers, including private section symbols."""
import hashlib
from pathlib import Path
import struct

REQUIRED = {
    '___ubsan_handle_add_overflow_minimal',
    '___ubsan_handle_negate_overflow_minimal',
    '___ubsan_handle_sub_overflow_minimal',
    '_mach_assert_jump_key',
}


def verify_diagnostic_providers(path):
    data = Path(path).read_bytes()
    if (len(data) < 32 or struct.unpack_from('<II', data) != (0xfeedfacf, 0x100000c)
            or struct.unpack_from('<I', data, 8)[0] & 0xffffff != 2
            or struct.unpack_from('<I', data, 12)[0] != 2):
        raise ValueError('Expected actual arm64e reference Mach-O')
    sections, symtab, at = [], None, 32
    commands, command_bytes = struct.unpack_from('<II', data, 16)
    end = 32 + command_bytes
    for _ in range(commands):
        kind, size = struct.unpack_from('<II', data, at)
        if size < 8 or at + size > end or end > len(data):
            raise ValueError('Reference command bounds')
        if kind == 0x19:
            count = struct.unpack_from('<I', data, at + 64)[0]
            if 72 + count * 80 > size:
                raise ValueError('Reference section bounds')
            for i in range(count):
                offset = at + 72 + i * 80
                name, segment, va, length, fileoff = struct.unpack_from('<16s16sQQI', data, offset)
                sections.append(dict(name=name.rstrip(b'\0').decode(), segment=segment.rstrip(b'\0').decode(),
                                     va=va, size=length, fileoff=fileoff))
        elif kind == 2:
            symtab = struct.unpack_from('<4I', data, at + 8)
        at += size
    if at != end or symtab is None:
        raise ValueError('Reference symbol table missing')
    symoff, count, strings, string_bytes = symtab
    if symoff + count * 16 > len(data) or strings + string_bytes > len(data):
        raise ValueError('Reference symbol table bounds')
    found = {}
    for i in range(count):
        strx, kind, section, desc, address = struct.unpack_from('<IBBHQ', data, symoff + 16 * i)
        if not strx or kind & 0xe0 or kind & 0x0e != 0x0e:
            continue  # Exclude debug, undefined, absolute and indirect names.
        if strx >= string_bytes:
            raise ValueError('Reference symbol string bounds')
        stop = data.index(b'\0', strings + strx, strings + string_bytes)
        name = data[strings + strx:stop].decode()
        if name not in REQUIRED:
            continue
        if name in found or not 1 <= section <= len(sections):
            raise ValueError('Ambiguous diagnostic definition: ' + name)
        s = sections[section - 1]
        width = 24 if name == '_mach_assert_jump_key' else 12
        offset = s['fileoff'] + address - s['va']
        if not s['va'] <= address <= s['va'] + s['size'] - width or offset + width > len(data):
            raise ValueError('Unbacked diagnostic definition: ' + name)
        body = data[offset:offset + width]
        if name == '_mach_assert_jump_key':
            if s['segment'] != '__DATA_CONST' or body != b'\0\0\1\0' + bytes(20):
                raise ValueError('Genuine enabled static-key initializer differs')
        elif s['segment'] != '__TEXT_EXEC' or struct.unpack('<3I', body) != (0xd503245f, 0xd43fe000, 0xd65f03c0):
            raise ValueError('Genuine BTI / brk #0xff00 / ret handler differs: ' + name)
        found[name] = dict(address=hex(address), n_type=hex(kind), section=s['name'], segment=s['segment'],
                           file_offset=offset, bytes=body.hex(), sha256=hashlib.sha256(body).hexdigest())
    missing = REQUIRED - found.keys()
    if missing:
        raise ValueError('Final RELEASE reference lacks genuine diagnostic definitions: ' + ', '.join(sorted(missing)))
    return found
