#!/usr/bin/env python3
"""Replay reviewed real bindings on retained clean inputs without compiling.

Use a new attempt directory. The exact native/reference/cache, pairing,
engine, fixtures, consumer contracts and original regression policy are
pinned in clean-prelink-contract.json. Incomplete images remain in memory.
"""
import argparse
import ast
import hashlib
import json
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path


CONTRACT = Path(__file__).with_name('clean-prelink-contract.json')
FIXTURE = Path(__file__).with_name('clean-prelink-symbols.json')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_pinned(path, expected, label):
    data = path.read_bytes()
    require(digest(data) == expected, label + ' identity changed; review this input before recovery')
    return data


def check_kit(kit, contract):
    for name, expected in contract['engine'].items():
        read_pinned(kit / name, expected, 'Prelink engine ' + name)
    fixtures = {p.name for p in (kit / 'fixtures').glob('fileset-*-symbols.json')}
    require(fixtures == set(contract['engine_fixtures']), 'Prelink fixture inventory changed')
    for name, expected in contract['engine_fixtures'].items():
        read_pinned(kit / 'fixtures' / name, expected, 'Prelink fixture ' + name)


def validate_inputs(data, contract):
    for name, expected in contract['inputs'].items():
        require(digest(data[name]) == expected, name + ' input identity changed')


def run_original_regression_check(source, record, policy):
    """Execute the retained production function, isolated from build imports."""
    tree = ast.parse(source)
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == 'check_prelink_regressions']
    require(len(definitions) == 1, 'Original regression function is unavailable')
    namespace = {'Error': ValueError}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), '<pinned regression check>', 'exec'), namespace)
    namespace['check_prelink_regressions'](record, policy)


def verify_bindings(image_bytes, raw, native_data, roots, early, document, bindings):
    """Decode actual relocated slots independently of the matcher's claims."""
    from kc_image import Image
    from fileset_emit import dependency_closure, rebase_collection
    from fileset_layout import Layout
    stock, native, output = Image(raw), Image(native_data), Image(image_bytes)
    closure = dependency_closure(stock, roots)
    rebased, slide, _ = rebase_collection(stock, native.base, closure, early, set(roots))
    layout = Layout(rebased, native, closure)
    names = {}
    for address, symbols in native.symbols().items():
        for name in symbols:
            names.setdefault(name, set()).add(address)

    def named(name):
        addresses = names.get(name, set())
        require(len(addresses) == 1, 'Missing/ambiguous recovered implementation: ' + name)
        return next(iter(addresses))

    original_fixups, final_fixups = stock.fixups(), output.fixups()
    member = Image(image_bytes, output.entries['com.apple.kernel'][1])
    output_symbols = member.symbols()
    objects = {row['native_symbol']: row for row in document['data']}
    records = []
    for binding in bindings:
        original_site = int(binding['site'], 16)
        original_target = int(binding['original'], 16)
        before = original_fixups[original_site]
        require(before[0] == original_target, 'Original import target changed')
        expected = layout.translate(named(binding['symbol']))
        site = (original_site + slide) & ((1 << 64) - 1)
        require(final_fixups.get(site) == (expected, *before[1:]),
                'Recovered import target/authentication changed')
        require(binding['symbol'] in output_symbols.get(expected, []), 'Output symbol mismatch')
        row = dict(binding, final_site=hex(site), final_target=hex(expected),
                   chain_fields=list(before[1:]), real_native_binding=True)
        if binding['symbol'] == '_kext_assertions_enable':
            require(struct.unpack('<I', output.read(expected, 4))[0] == 1,
                    'Native DEVELOPMENT assertions were disabled')
            row['integer_value'] = 1
        if binding['symbol'] == '_PE_arm_debug_panic_hook':
            hook = objects[binding['symbol']]['native_fixup']
            handler = layout.translate(named(hook['symbol']))
            require(final_fixups.get(expected) == (handler, *hook['fields']),
                    'Native real panic handler/authentication changed')
            row['real_handler'] = dict(symbol=hook['symbol'], target=hex(handler), fields=hook['fields'])
        records.append(row)
    return records


def publish(image, report, output, report_path, regression_source, policy):
    from fileset_emit import atomic_write, write_candidate
    require(not output.exists(), 'Refuse to overwrite an existing candidate')
    # These extra conditions strengthen strict publication. The production
    # report and its loadable/runtime constants are preserved verbatim.
    if report.get('stubbed') or report.get('statistics', {}).get('unproven_kernel_page_references', 0):
        report.update(output=str(output.resolve()), candidate_written=False)
        atomic_write(report_path, (json.dumps(report, indent=2) + '\n').encode())
        raise ValueError('Refuse a stubbed or unproven-page candidate')
    if not report['missing']:
        try:
            run_original_regression_check(regression_source, report, policy)
        except ValueError:
            report.update(output=str(output.resolve()), candidate_written=False)
            atomic_write(report_path, (json.dumps(report, indent=2) + '\n').encode())
            raise
    write_candidate(image, report, output, report_path, allow_missing=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('kit', 'kernelcache', 'native', 'reference', 'map', 'policy', 'regression-source', 'attempt'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args(argv)
    contract = json.loads(CONTRACT.read_text(encoding='utf-8'))
    require(not args.attempt.exists(), 'Use a new attempt directory; preserve previous failures')
    attempt = args.attempt.resolve()
    inputs = {name: getattr(args, name).resolve(strict=True) for name in
              ('kit', 'kernelcache', 'native', 'reference', 'map', 'policy', 'regression_source')}
    require(all(not path.is_relative_to(attempt) for path in inputs.values()), 'Inputs must be outside the attempt')
    attempt.mkdir(parents=True, exist_ok=False)
    receipt = dict(started_at=datetime.now(timezone.utc).isoformat(), status='validating',
                   inputs={name: str(path) for name, path in inputs.items()},
                   contract_sha256=digest(CONTRACT.read_bytes()),
                   build_invoked=False, device_operations=False, candidate_persisted=False)
    failure = None
    try:
        check_kit(inputs['kit'], contract)
        read_pinned(Path(__file__).with_name('m4_prelink_evidence.py'), contract['interface_guard_sha256'], 'Interface guard')
        fixture = read_pinned(FIXTURE, contract['reviewed_fixture_sha256'], 'Reviewed clean fixture')
        data = {name: inputs[name].read_bytes() for name in contract['inputs']}
        validate_inputs(data, contract)
        receipt['input_identities_verified'] = True
        policy = read_pinned(inputs['policy'], contract['regression_policy_sha256'], 'Regression policy')
        regression_source = read_pinned(inputs['regression_source'], contract['regression_source_sha256'], 'Regression source')
        document = json.loads(fixture)
        # Copy only verified modules and fixtures. The original kit is read-only.
        staged = attempt / 'prelink'
        (staged / 'fixtures').mkdir(parents=True)
        for name in contract['engine']:
            shutil.copyfile(inputs['kit'] / name, staged / name)
        for name in contract['engine_fixtures']:
            shutil.copyfile(inputs['kit'] / 'fixtures' / name, staged / 'fixtures' / name)
        (staged / 'fixtures' / contract['fixture_name']).write_bytes(fixture)
        sys.path.insert(0, str(staged))
        from m4_prelink_evidence import validate
        from kc_image import Image
        from fileset_emit import dependency_closure, emit_images
        roots = contract['roots']
        early = {name: int(address, 16) for name, address in contract['early_security_init'].items()}
        closure = dependency_closure(Image(data['kernelcache']), roots)
        receipt['interface_guard'] = validate(document, data['kernelcache'], data['native'], closure)
        pairing = json.loads(data['map'])
        require(pairing['reference_sha256'] == digest(data['reference']), 'Pairing reference identity changed')
        image, report = emit_images(data['kernelcache'], data['native'], pairing, roots,
                                    early_security_init=early)
        require(report['missing'] == contract['known_remaining'], 'Exact-input emission changed its unresolved set')
        receipt['recovered_bindings'] = verify_bindings(image, data['kernelcache'], data['native'], roots,
                                                       early, document, contract['bindings'])
        receipt.update(recovered_import_occurrences=len(receipt['recovered_bindings']),
                       remaining=report['missing'], stubbed=report['stubbed'],
                       in_memory_candidate_sha256=report['candidate_sha256'])
        for name, expected in contract['inputs'].items():
            read_pinned(inputs[name], expected, name)
        publish(image, report, attempt / 'kernel.macho', attempt / 'kernel.json', regression_source, json.loads(policy))
        receipt.update(status='strict_candidate_written_runtime_unqualified', candidate_persisted=True)
    except Exception as error:
        failure = str(error)
        receipt.update(status='refused', error=failure)
    finally:
        receipt['source_inputs_modified'] = False
        for name, expected in contract['inputs'].items() if receipt.get('input_identities_verified') else ():
            if not inputs[name].is_file() or digest(inputs[name].read_bytes()) != expected:
                receipt['source_inputs_modified'] = True
                # Unknown input rejection is already recorded; a verified
                # input changing during emission is a separate fatal error.
                if failure is None:
                    failure = name + ' input changed during recovery'
                    receipt.update(status='refused', error=failure)
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        (attempt / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    if failure:
        print(failure, file=sys.stderr)
        return 1
    print('Strict candidate written; runtime qualification remains pending')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
