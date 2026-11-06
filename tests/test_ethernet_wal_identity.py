"""Read-only identity fixtures captured from the disposable exact-version K3s WALs."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "wal_identity", Path(__file__).resolve().parents[1] / "scripts/ethernet_wal_identity.py"
)
W = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(W)
# Only immutable public identity headers, no keys or committed application data.
HEADERS = [
    bytes.fromhex(
        "040000000000008408041000000000001f00000000000081080110ade0a2ad0c1a1508"
        "d69bedd5c38c9cfd5e10ebeabbdbf8f2e9ffdc0100"
    ),
    bytes.fromhex(
        "040000000000008408041000000000001f00000000000081080110dfc1c7870b1a1508"
        "fbb9caffa5b581b7bd0110b4cac79ef0eafdf46e00"
    ),
]
IDENTITIES = [
    {"member_id": "6843906159527284182", "cluster_id": "15924631076726568299"},
    {"member_id": "13649853749918866683", "cluster_id": "7992190966843958580"},
]


@pytest.mark.parametrize("index", [0, 1])
def test_actual_k3s_headers_and_no_writes(tmp_path, index):
    path = tmp_path / "0000000000000000-0000000000000000.wal"
    path.write_bytes(HEADERS[index] + b"unread committed data")
    path.chmod(0o400)
    before = path.stat()
    assert W.identity(tmp_path) == IDENTITIES[index]
    after = path.stat()
    assert (before.st_ino, before.st_mtime_ns, before.st_size) == (
        after.st_ino,
        after.st_mtime_ns,
        after.st_size,
    )
    assert path.read_bytes() == HEADERS[index] + b"unread committed data"


def test_conflicting_original_identities_refused(tmp_path):
    for index, data in enumerate(HEADERS):
        (tmp_path / f"{index:016x}-0000000000000000.wal").write_bytes(data)
    with pytest.raises(ValueError, match="conflicting"):
        W.identity(tmp_path)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        HEADERS[0][:20],
        b"\xff" * 8,
        HEADERS[0][:-1],
        HEADERS[0][:40] + b"\x00" + HEADERS[0][41:],
    ],
)
def test_missing_torn_or_corrupt_identity_is_never_authorized(tmp_path, data):
    path = tmp_path / "0000000000000000-0000000000000000.wal"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        W.identity(tmp_path)
    assert path.read_bytes() == data


def test_missing_or_symlinked_wal_is_refused(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        W.identity(tmp_path)
    target = tmp_path / "header"
    target.write_bytes(HEADERS[0])
    (tmp_path / "0000000000000000-0000000000000000.wal").symlink_to(target)
    with pytest.raises(OSError):
        W.identity(tmp_path)


def test_crc32c_known_vector_and_seed_composition():
    assert W.crc32c(b"123456789") == 0xE3069283
    assert W.crc32c(b"56789", W.crc32c(b"1234")) == 0xE3069283


@pytest.mark.parametrize(
    "wire",
    [
        b"\x08\x80",
        b"\x08" + b"\xff" * 9 + b"\x02",
        b"\x08" + b"\x80" * 10,
        b"\x00\x00",
        b"\x08\x01\x08\x02",
        b"\x0a\x05a",
        b"\x0d",
    ],
)
def test_identity_parser_rejects_ambiguous_or_unbounded_protobuf(wire):
    with pytest.raises(ValueError):
        W.fields(wire)


def test_invalid_frames_and_identity_types_are_read_only(tmp_path, monkeypatch):
    import io
    import struct
    from types import SimpleNamespace

    record = b"\x08\x04"  # Missing checksum field.
    framed = struct.pack("<Q", len(record) | ((0x80 | 6) << 56)) + record + b"\0" * 6
    with pytest.raises(ValueError, match="invalid WAL identity record"):
        W.frame(io.BytesIO(framed))
    path = tmp_path / "0000000000000000-0000000000000000.wal"
    path.write_bytes(HEADERS[0])
    monkeypatch.setattr(W.os, "fstat", lambda fd: SimpleNamespace(st_mode=0o040755))
    with pytest.raises(ValueError, match="regular file"):
        W.segment_identity(path)
    monkeypatch.undo()
    for payload in (b"\x08\x00\x10\x01", b"\x08\x01", b"\x0a\x01x\x10\x01"):
        records = iter([{1: 4, 2: 0}, {1: 1, 2: W.crc32c(payload), 3: payload}])
        monkeypatch.setattr(W, "frame", lambda _: next(records))
        with pytest.raises(ValueError, match="member/cluster identity"):
            W.segment_identity(path)
    assert path.read_bytes() == HEADERS[0]
    path.rename(tmp_path / "invalid.wal")
    with pytest.raises(ValueError, match="segment name"):
        W.identity(tmp_path)
    with pytest.raises(ValueError, match="initialized WAL"):
        W.identity(tmp_path / "missing")
