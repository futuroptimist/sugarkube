"""Read only the two immutable header records of etcd 3.6.7 WAL segments.

This is an identity gate, not a WAL integrity checker or repair tool. Never open
for writing, replay entries, repair, truncate or create any database/WAL path.
Format references (k3s-io/etcd 9f7f2c9540f1211570c2f23fd0baafc1d537662d):
server/storage/wal/{encoder.go,decoder.go,walpb/record.proto},
api/etcdserverpb/etcdserver.proto (Metadata). Upstream license: vendor/etcd/LICENSE.
"""

import os
import re
import stat
import struct


def crc32c(data, seed=0):
    value = seed ^ 0xFFFFFFFF
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0x82F63B78 if value & 1 else 0)
    return value ^ 0xFFFFFFFF


def fields(data):
    """Narrow protobuf varint/bytes reader; reject duplicate or unknown wire types."""
    position, result = 0, {}

    def varint():
        nonlocal position
        value = 0
        for shift in range(0, 70, 7):
            if position >= len(data):
                raise ValueError("truncated identity record")
            byte = data[position]
            position += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                if value > 0xFFFFFFFFFFFFFFFF:
                    raise ValueError("identity integer overflow")
                return value
        raise ValueError("oversized identity varint")

    while position < len(data):
        tag = varint()
        number, wire = tag >> 3, tag & 7
        if not number or number in result:
            raise ValueError("duplicate/invalid identity field")
        if wire == 0:
            value = varint()
        elif wire == 2:
            size = varint()
            if size > len(data) - position:
                raise ValueError("truncated identity bytes")
            value = data[position : position + size]
            position += size
        else:
            raise ValueError("unsupported identity wire type")
        result[number] = value
    return result


def frame(handle):
    prefix = handle.read(8)
    if len(prefix) != 8:
        raise ValueError("missing WAL identity header")
    header = struct.unpack("<Q", prefix)[0]
    size, high = header & ((1 << 56) - 1), header >> 56
    padding = (-size) % 8
    if not 0 < size <= 1024 or high != (0x80 | padding if padding else 0):
        raise ValueError("invalid WAL identity frame")
    data = handle.read(size + padding)
    if len(data) != size + padding or any(data[size:]):
        raise ValueError("truncated or invalid WAL identity padding")
    record = fields(data[:size])
    if not {1, 2} <= set(record) <= {1, 2, 3} or not isinstance(record[2], int):
        raise ValueError("invalid WAL identity record")
    return record


def segment_identity(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("WAL identity input is not a regular file")
        seed, metadata = frame(handle), frame(handle)
    if (
        seed[1] != 4
        or seed.get(3, b"") != b""
        or seed[2] > 0xFFFFFFFF
        or metadata[1] != 1
        or not isinstance(metadata.get(3), bytes)
        or crc32c(metadata[3], seed[2]) != metadata[2]
    ):
        raise ValueError("invalid WAL metadata type/checksum")
    identity = fields(metadata[3])
    if set(identity) != {1, 2} or any(type(v) is not int or v == 0 for v in identity.values()):
        raise ValueError("invalid WAL member/cluster identity")
    return {"member_id": str(identity[1]), "cluster_id": str(identity[2])}


def identity(directory):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("initialized WAL directory required")
    paths = sorted(directory.glob("*.wal"))
    if not 1 <= len(paths) <= 64:
        raise ValueError("missing or excessive WAL segments")
    identities = []
    for path in paths:
        if not re.fullmatch(r"[0-9a-f]{16}-[0-9a-f]{16}\.wal", path.name):
            raise ValueError("unexpected WAL segment name")
        identities.append(segment_identity(path))
    if any(value != identities[0] for value in identities):
        raise ValueError("conflicting WAL identities")
    return identities[0]
