"""Check the native binary and the proposed registry index before promotion."""

import re
import struct
import sys


MACHINES = {"amd64": 62, "arm64": 183}
INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
MANIFEST_TYPES = {
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
}


def verify_elf(data, architecture):
    if (len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01"
            or struct.unpack_from("<I", data, 20)[0] != 1
            or struct.unpack_from("<H", data, 52)[0] != 64):
        raise ValueError("expected a little-endian ELF64 binary")
    if struct.unpack_from("<H", data, 18)[0] != MACHINES[architecture]:
        raise ValueError("ELF architecture mismatch")
    if b"WebhookDelivery/1.0\0" not in data:
        raise ValueError("missing webhook User-Agent")


def verify_index(index, expected):
    if index.get("schemaVersion") != 2 or index.get("mediaType") not in INDEX_TYPES:
        raise ValueError("invalid multiarch index")
    manifests = index.get("manifests")
    if not isinstance(manifests, list) or len(manifests) != len(MACHINES):
        raise ValueError("expected exactly two runnable manifests")

    children = {}
    for child in manifests:
        platform = child.get("platform", {})
        arch = platform.get("architecture")
        variant = platform.get("variant", "")
        digest = child.get("digest", "")
        if (platform.get("os") != "linux" or arch not in MACHINES or arch in children
                or variant not in ({"", "v8"} if arch == "arm64" else {""})
                or child.get("mediaType") not in MANIFEST_TYPES
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
            raise ValueError("unexpected platform or image descriptor")
        children[arch] = digest
    if children != expected or len(set(children.values())) != len(MACHINES):
        raise ValueError("manifest digests do not match the qualified pair")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("architecture", choices=MACHINES)
    args = parser.parse_args()
    verify_elf(sys.stdin.buffer.read(), args.architecture)
