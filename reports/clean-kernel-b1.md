# Clean kernel B1 experiment

Run 43606241244 compiled XNU from fresh checkouts at device 1281f0f4 and framework
97437dcf. It stopped at the bootstrap link with 12 symbols supplied by later
archives. The attempt archive SHA-256 is
0c698052005c27a937fbf7c4bd75d74f2428af524471b2544cb3373145f0bc2a.

The experiment branch uses the registered prebuild-audit.yml manual entry.
No source pins, compiler targets, final linker options or prelink policies change.
The original framework expects bootstrap link failure before building archives.
The observer now permits only the reviewed exact symbol set, no preceding
compiler errors, the expected LD target, and fresh complete filelist objects.
All other failures stop. JSON evidence records the guard's decision.

Local tests cover the real prior log, injected compiler errors, unknown symbols,
other linker errors, wrong bootstrap mode, missing/stale objects, retained patch
trees, retained prelink candidates and child exit recording. A subsequent run
must use a new hosted VM and may not restore objects from the previous attempt.
Complete compilation, final link, prelink and device boot remain unverified.

Run 43607616395 accepted the precise bootstrap failure, then compiled both
CoreCrypto variants from 529 C sources each. Display archive 19 stopped when
the helper path resolved to current/scripts instead of current/UniXNU/scripts.
The isolated sibling output directory exposed the fallback's layout assumption.
Its original attempt SHA-256 is
c2ab436f3440b59a08b4c557c05adbe8c099df365f4b719e5c34af3afa2896df.

The harness now explicitly exports the verified framework and device paths.
It checks the source-driver helper stays in the pinned framework and matches
its recorded SHA-256 before running compatibility, fetch or compilation.
source-paths.json records these inputs. scripts/repro/test_paths.py checks
child-process inheritance, a missing or changed helper and an external symlink.
Each subsequent attempt starts with a new hosted runner and empty project
objects. Original errors, repair diffs, validation and artifacts are retained.
