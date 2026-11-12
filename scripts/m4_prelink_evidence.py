"""Fail-closed checks for reviewed M4 interface evidence, without changing an input image."""
import hashlib
import json
import struct


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def section_flags(image, section):
    for command, offset, _ in image.commands:
        if command != 0x19:
            continue
        count = struct.unpack_from('<I', image.data, offset + 64)[0]
        for index in range(count):
            at = offset + 72 + index * 80
            address = struct.unpack_from('<Q', image.data, at + 32)[0]
            name = image.data[at:at + 16].split(b'\0')[0].decode()
            if address == section['va'] and name == section['name']:
                return struct.unpack_from('<I', image.data, at + 64)[0]
    raise ValueError('No section flags for reviewed object')


def object_bytes(image, address, size, zerofill=False):
    section = image.section(address)
    require(section is not None and address + size <= section['va'] + section['size'],
            'Reviewed object is not contained in one section')
    is_zerofill = section_flags(image, section) & 0xff == 1
    require(is_zerofill == zerofill, 'Reviewed object backing changed')
    return bytes(size) if is_zerofill else image.read(address, size)


def validate(document, raw, native_data, closure):
    from kc_image import Image, scan
    cache = Image(raw)
    original = Image(raw, cache.entries['com.apple.kernel'][1])
    native = Image(native_data)
    require(digest(raw) == document['inputs']['kernelcache_sha256'], 'Reviewed kernelcache digest changed')
    names = {}
    for address, symbols in native.symbols().items():
        for name in symbols:
            names.setdefault(name, set()).add(address)

    def named(name):
        found = names.get(name, set())
        require(len(found) == 1, 'Missing/ambiguous reviewed native symbol: ' + name)
        return next(iter(found))

    for row in document['functions']:
        address = int(row['original'], 16)
        require(address in original.function_starts(), 'Reviewed original is not a function start')
        starts = original.function_starts()
        index = starts.index(address)
        require(starts[index + 1] - address == row['original_size'], 'Reviewed original extent changed')
        require(digest(original.read(address, row['original_size'])) == row['original_sha256'],
                'Reviewed original function bytes changed')
        target = named(row['native_symbol'])
        if 'native_sha256' in row:
            require(digest(native.read(target, row['native_size'])) == row['native_sha256'],
                    'Reviewed native implementation changed: ' + row['native_symbol'])

    objects = []
    for row in document['data']:
        address, target = int(row['original'], 16), named(row['native_symbol'])
        require(address % row['original_alignment'] == 0 and target % row['native_alignment'] == 0,
                'Reviewed data alignment changed')
        require(object_bytes(original, address, row['original_size'], row.get('original_zerofill', False)).hex()
                == row['original_bytes'], 'Reviewed original object content changed')
        require(object_bytes(native, target, row['native_size'], row.get('native_zerofill', False)).hex()
                == row['native_bytes'], 'Reviewed native object content changed')
        if 'native_fixup' in row:
            expected = row['native_fixup']
            require(native.fixups().get(target) == (named(expected['symbol']), *expected['fields']),
                    'Reviewed native hook target/authentication changed')
        objects.append({'symbol': row['native_symbol'], 'original': hex(address), 'native': hex(target),
                        'size': row['native_size'], 'native_bytes': row['native_bytes']})

    # The original adds flavor 3. Only the proven BASIC_INFO consumer may use
    # this map: do not silently qualify the newer flavor or broaden its users.
    contract = document['processor_info_contract']
    require(digest(json.dumps(sorted(closure), separators=(',', ':')).encode()) == contract['closure_sha256'],
            'Closure changed: review processor_info flavor contract again')
    consumer = contract['consumer']
    member = Image(raw, cache.entries[consumer][1])
    begin = int(contract['caller_begin'], 16)
    require(digest(member.read(begin, contract['caller_size'])) == contract['caller_sha256'],
            'processor_info caller bytes changed')
    target, got, stub, call = (int(contract[k], 16) for k in ('original', 'got', 'stub', 'call'))
    require(struct.unpack('<I', member.read(call - 4, 4))[0] == 0x52800021,
            'processor_info call no longer establishes flavor 1')
    require(struct.unpack('<I', member.read(0xfffffe00087170ac, 4))[0] == 0x528000b6,
            'processor_info caller no longer initializes count 5')
    imports, callers = set(), set()
    fixups = cache.fixups()
    for name in closure:
        if name == 'com.apple.kernel' or name not in cache.entries:  # Codeless KPI dependencies have no Mach-O.
            continue
        image = Image(raw, cache.entries[name][1])
        for site, fixup in fixups.items():
            if fixup[0] == target and any(s['name'] != '__LINKEDIT' and s['va'] <= site < s['va'] + s['size']
                                          for s in image.segments):
                imports.add((name, site))
        for segment in image.segments:
            if segment['name'] not in ('__TEXT_EXEC', '__TEXT_BOOT_EXEC', '__KLD', '__LAST') or not segment['filesize']:
                continue
            calls, _, _ = scan(image.read(segment['va'], segment['filesize']), segment['va'])
            for pc, destination, _ in calls:
                require(destination != target, 'Additional direct processor_info consumer requires review')
                if destination == stub:
                    callers.add((name, pc))
    require(imports == {(consumer, got)} and callers == {(consumer, call)},
            'Additional processor_info import/call requires ABI review')
    fix = fixups[got]
    require(fix[0] == target and fix[1:] == (1, 0, 0, 1), 'processor_info authenticated import changed')
    words = struct.unpack('<4I', member.read(stub, 16))
    require(words[0] & 0x9f00001f == 0x90000011 and words[1] & 0xffc003ff == 0x91000231
            and words[2:] == (0xf9400230, 0xd71f0a11), 'processor_info import veneer ABI changed')

    # Prove the non-monitor storage backend supplies real writable, sufficiently
    # large initialized storage; do not bind this interface to its TXM panic body.
    storage = named('__xnu_image4_storage')
    require(storage % 8 == 0 and object_bytes(native, storage, 0x1400, True) == bytes(0x1400),
            'Image4 storage allocation size/alignment/initialization changed')
    return {'reviewed_functions': len(document['functions']), 'reviewed_objects': objects,
            'processor_info': {'qualified_flavors': [1], 'flavor_3_qualified': False,
                               'consumer': consumer, 'call': hex(call), 'count': 5},
            'image4_storage': {'bytes': 0x1400, 'required_bytes': 0x390, 'alignment': 8}}
