# Image4 adapter code size

The retained strict layout has no spare mapped code pages. The candidate exceeds it by one 16 KiB page: its last executable section ends four bytes beyond the old segment capacity. Six normal Image4 adapter functions now request Clang minsize code generation. Their C statements, locking, errors, panic paths, PAC types and interfaces are unchanged. No whole-kernel configuration or layout checks are changed.

The exact updated source passes all 37 existing host checks with optimization enabled, including five panic conditions and backend error and mirror-consumer cases. Host results do not establish arm64e code size or runtime behavior. The clean native build and strict prelink must independently prove the size reduction and all final bindings before packaging can qualify a boot candidate.

Baseline evidence is read from the hash-pinned sealed extraction of run 43715522445, preserving the exact original native and kernel.py hashes. No archived objects enter clean compilation.
