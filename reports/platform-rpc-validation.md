# Dictionary platform RPC experiment

The retained 24A446 AppleARMPlatform import at `0xfffffe000b433e68`
currently calls the prelink panic replacement. Public XNU 12377 lacks the
dictionary DriverKit platform RPC. The original interface has ID
`0xbf66f4287c60ef85` and signature
`IOService::CallPlatformFunction(OSString*, bool, OSDictionary*, OSDictionary**, OSDispatchMethod)`.

The experimental patch restores the IDL and the observed functional backend:
TLS platform-driver checks, cross-owner RPC routing, a typed callback queried
with `IOUserPlatformFunctionHandlerGet`, rejection of the incompatible legacy
method, symbol lifetime and callback result propagation. It is not in the
selected patch series pending real generation, wire, pointer-authentication
and behavioral validation. It does not supply Qualcomm platform handlers.

The manual experimental `prebuild-audit.yml` now restores only the relevant
source, headers and objects from successful clean run `43615501493`. It
checks the archive and Apple compiler identities, regenerates the original
IDL byte for byte, generates the experimental IDL, checks unchanged method
IDs, and compiles three actual arm64e translation units. Sources, full diff,
commands, diagnostics, objects and disassembly are retained even on failure.
No clean full build, prelink, payload builder or device operation is invoked.

Object compilation does not qualify the RPC wire, backend behavior or boot.
The original request uses three descriptors and object references, send size
`0x8c`, reply size `0x54`, and flags `0x100`; those details require independent
comparison. Image4 nonce/trust interfaces and an exact new boot image remain
separate unresolved requirements. The emitter's `loadable=false` is a
constant, not evidence of an observed loader rejection.
