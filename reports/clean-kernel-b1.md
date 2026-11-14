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
