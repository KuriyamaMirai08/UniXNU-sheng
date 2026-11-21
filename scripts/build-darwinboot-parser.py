#!/usr/bin/env python3
"""Build a host executable from the pinned production DarwinBoot parser."""

import argparse
import hashlib
import subprocess
from pathlib import Path

PINNED_SOURCE_SHA256 = "1d19ca1091962bd48b4154e3aae3d0ad80699f6c892a5a407dd3de0d62907fd9"
SHIM = r"""
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
typedef uint8_t UINT8;
typedef uint32_t UINT32;
typedef uint64_t UINT64;
typedef size_t UINTN;
typedef int BOOLEAN;
typedef int EFI_STATUS;
#define STATIC static
#define CONST const
#define FALSE 0
#define TRUE 1
#define EFI_SUCCESS 0
#define EFI_LOAD_ERROR 1
#define EFI_UNSUPPORTED 2
#define EFI_ERROR(s) ((s) != EFI_SUCCESS)
#define EFI_PAGE_MASK 4095u
#define MAX_UINT64 UINT64_MAX
#define SIZE_2MB (2u << 20)
#define SIZE_256MB (256u << 20)
#define MIN(a,b) ((a) < (b) ? (a) : (b))
#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define ZeroMem(ptr,n) memset((ptr), 0, (n))
#define CompareMem memcmp
static UINT32 U32(const void *p) { UINT32 v; memcpy(&v,p,sizeof(v)); return v; }
static UINT64 U64(const void *p) { UINT64 v; memcpy(&v,p,sizeof(v)); return v; }
"""
MAIN = r"""
int main(void) {
#ifdef _WIN32
  if (_setmode(_fileno(stdin), _O_BINARY) == -1) return 2;
#endif
  UINT8 *data = malloc(KERNEL_LIMIT);
  if (!data) return 2;
  size_t length = fread(data, 1, KERNEL_LIMIT, stdin);
  if (ferror(stdin) || length == KERNEL_LIMIT) { free(data); return 2; }
  KERNEL kernel;
  EFI_STATUS status = ParseKernel(data, length, &kernel);
  if (!EFI_ERROR(status))
    printf("DarwinBoot parser PASS root_segments=%zu span=%" PRIu64 " entry=%" PRIx64 "\n",
           kernel.Count, kernel.End - kernel.Base, kernel.Entry);
  else
    fprintf(stderr, "DarwinBoot parser REJECT status=%d\n", status);
  free(data);
  return status;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--compiler", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-source", type=Path, required=True)
    args = parser.parse_args()
    source_bytes = args.source.read_bytes()
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    if actual_hash != PINNED_SOURCE_SHA256:
        raise SystemExit(f"DarwinBoot source SHA-256 mismatch: {actual_hash}")
    source = source_bytes.decode("utf-8")
    constants = source[source.index("#define WINDOW_SIZE"):source.index("// Where the parts")]
    start = source.index("STATIC\nEFI_STATUS\nParseKernelHeader")
    end = source.index("STATIC\nBOOLEAN\nAdtNode", start)
    args.generated_source.parent.mkdir(parents=True, exist_ok=True)
    args.generated_source.write_text(SHIM + constants + source[start:end] + MAIN, encoding="utf-8", newline="\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([args.compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    str(args.generated_source), "-o", str(args.output)], check=True)


if __name__ == "__main__":
    main()
