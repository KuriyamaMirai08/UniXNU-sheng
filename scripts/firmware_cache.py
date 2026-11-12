"""Validate retained public firmware inputs before accepting a deleted archive."""
import hashlib
import json
from pathlib import Path


def verified_retained(directory, image):
    directory = Path(directory)
    record_path = directory / 'porting-inputs.json'
    if not record_path.is_file():
        return False
    record = json.loads(record_path.read_text())
    if not record.get('archive_deleted'):
        return False
    if (record.get('source_url') != image['url'] or record.get('archive_sha256') != image['sha256']
            or record.get('archive_bytes') != image['bytes'] or not record.get('gzip_integrity_verified')):
        raise ValueError('Retained firmware provenance differs; preserve and inspect this cache')
    selected = record.get('selected', [])
    names = set()
    for entry in selected:
        name = entry['file']
        if not name or Path(name).name != name or '/' in name or '\\' in name or name in names:
            raise ValueError('Invalid or duplicate retained firmware filename')
        names.add(name)
        path = directory / 'porting-inputs' / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['bytes']:
            raise ValueError('Retained firmware input missing or wrong size: ' + name)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != entry['sha256']:
            raise ValueError('Retained firmware input SHA-256 mismatch: ' + name)
    if not names or 'uefi.elf' not in names:
        raise ValueError('Retained firmware inventory lacks uefi.elf')
    return True


def required_free_bytes(archive_bytes, already_allocated=0):
    # Extraction explicitly caps retained input at 2 GiB. Keep 512 MiB for
    # manifests and UEFI extraction alongside the archive, without deleting it.
    return max(0, archive_bytes - already_allocated) + (2 << 30) + (512 << 20)
