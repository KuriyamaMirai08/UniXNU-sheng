"""Exact pinned CoreCrypto builder transform: cache successful objects by real clang dependencies."""
import ast

OLD = '''    result = subprocess.run([*command, '-c', source, '-o', destination], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    (object_dir / (name + '.log')).write_text(result.stdout)
    return {'source': relative, 'object': destination.name, 'exit_code': result.returncode,
            'diagnostic': result.stdout[-2500:] if result.returncode else None}'''
NEW = '''    import shlex
    metadata = object_dir / (name + '.inputs.json')
    depfile = object_dir / (name + '.d')
    signature = [*command, str(source), compiler_identity]
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if metadata.is_file() and destination.is_file():
        cached = json.loads(metadata.read_text())
        if (cached.get('command') == signature and cached.get('object') == digest(destination)
                and all(Path(p).is_file() and digest(p) == value for p, value in cached.get('dependencies', {}).items())
                and str(source) in cached.get('dependencies', {})):
            return {'source': relative, 'object': destination.name, 'exit_code': 0, 'diagnostic': None, 'reused': True}
    temporary = destination.with_suffix('.new.o')
    result = subprocess.run([*command, '-MD', '-MF', str(depfile), '-c', source, '-o', temporary], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    (object_dir / (name + '.log')).write_text(result.stdout)
    if result.returncode == 0:
        # Clang's make-style dependencies cover generated Kernel.framework,
        # source/private headers AND SDK headers. Preserve old successful
        # objects/metadata when compilation fails; never accept them for this run.
        deps = shlex.split(depfile.read_text().replace('\\\\\\n', '').split(':', 1)[1])
        dependencies = {str(Path(p).resolve()): digest(p) for p in deps}
        dependencies[str(source)] = digest(source)
        temporary.replace(destination)
        metadata.write_text(json.dumps({'command': signature, 'dependencies': dependencies, 'object': digest(destination)}, sort_keys=True))
    return {'source': relative, 'object': destination.name, 'exit_code': result.returncode,
            'diagnostic': result.stdout[-2500:] if result.returncode else None, 'reused': False}'''


def transform(source):
    if source.count(OLD) != 1:
        raise ValueError('Pinned CoreCrypto compile_one changed; review before adapting')
    result = source.replace(OLD, NEW)
    marker = 'with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:'
    if result.count(marker) != 1:
        raise ValueError('Pinned CoreCrypto executor changed')
    result = result.replace(marker, "compiler_identity = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', 'clang', '--version'], text=True)\n\n" + marker)
    result = result.replace("failed = [result for result in results if result['exit_code']]",
                            "print('CoreCrypto objects reused: ' + str(sum(bool(r.get('reused')) for r in results)) + '/' + str(len(results)), flush=True)\nfailed = [result for result in results if result['exit_code']]")
    ast.parse(result)
    return result
