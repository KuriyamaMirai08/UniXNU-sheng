The boot candidate branch starts at 3454f946be90bfe2fabd5aeb1d01a85ee72726cc.
No complete replacement kernel or boot image exists at this checkpoint.

The retained RPC compilation failed because MACH_PORT_VALID compares a numeric
mach_port_name_t with the kernel's nullptr MACH_PORT_NULL. The isolated source
now checks numeric zero and MACH_PORT_DEAD directly. Both invalid name checks
remain. The original error, original patch, full new patch and source baseline
are archived locally under outputs/boot-candidate-20261115/rpc-repair-01.
The patch remains outside series pending object and wire validation.

The pinned author framework has no consumer for its Image4 V2 registration
table. Exact 24A446 Image4 instructions contain a normal, monitor-free PAL with
real certificate and local-policy evaluation. Reusing this path requires proof
that nonce state is consumed by verification, proper buffer lifetime, callback
authentication, and equivalent error handling. No constant-success or fixed-error
replacement is selected.

The existing clean workflow still builds the historical device revision and
stops after kernel prelink. Full source selection and the author's unchanged
release/package stages must be connected before any new image can be claimed.
The M4 runner is offline; the successful hosted clean-build archive and original
Data seed cache remain available. Seed content and device identity are private.

No device operation or stable-image change is authorized or performed.
