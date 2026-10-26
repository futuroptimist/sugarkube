#!/usr/bin/env python3
"""Reproduce the vendored wire schema from the exact etcd source manifest.

Usage: python scripts/generate_ethernet_etcd_descriptor.py /path/to/etcd-checkout
No network access; source hashes must match before any output is written.
The original Apache-2.0 license is in scripts/vendor/etcd/LICENSE.
"""

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool


def generate(source, destination):
    manifest = json.loads(
        Path(__file__).with_name("vendor").joinpath("etcd/descriptor.json").read_text()
    )
    descriptors = descriptor_pb2.FileDescriptorSet()
    for name, entry in manifest["files"].items():
        raw = (source / entry["source"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["go_sha256"]:
            raise ValueError("source hash mismatch: " + entry["source"])
        block = re.search(r"var fileDescriptor_\w+ = \[\]byte\{(.*?)\n\}", raw.decode(), re.S)
        wire = gzip.decompress(bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})", block[1])))
        if hashlib.sha256(wire).hexdigest() != entry["original_descriptor_sha256"]:
            raise ValueError("original descriptor hash mismatch")
        descriptor = descriptor_pb2.FileDescriptorProto.FromString(wire)
        # Strip Go/OpenAPI-only annotations, retaining all wire fields, oneofs,
        # messages and service definitions. Normalize the three import paths.
        descriptor.DiscardUnknownFields()
        descriptor.ClearField("dependency")
        descriptor.name = name + ".proto"
        if name == "rpc":
            descriptor.dependency.extend(["kv.proto", "auth.proto"])
        descriptors.file.append(descriptor)
    pool = descriptor_pool.DescriptorPool()
    for descriptor in descriptors.file:
        pool.Add(descriptor)
    result = descriptors.SerializeToString()
    if hashlib.sha256(result).hexdigest() != manifest["descriptor_sha256"]:
        raise ValueError("generated descriptor hash mismatch")
    destination.write_bytes(result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path(__file__).with_name("ethernet-etcd.desc")
    )
    args = parser.parse_args()
    generate(args.source, args.output)
