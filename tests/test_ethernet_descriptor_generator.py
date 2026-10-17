"""Deterministic wire-schema generation and fail-before-publication checks."""

import gzip
import hashlib
import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest
from google.protobuf import descriptor_pb2

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate_ethernet_etcd_descriptor.py"
SPEC = importlib.util.spec_from_file_location("descriptor_generator", SCRIPT)
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


@pytest.mark.parametrize("damage", [None, "source", "wire", "result"])
def test_generation_hashes_every_stage_before_writing(tmp_path, monkeypatch, damage):
    manifest = {"files": {}}
    expected = descriptor_pb2.FileDescriptorSet()
    for name in ("kv", "auth", "rpc"):
        original = descriptor_pb2.FileDescriptorProto(name=name + "/old.proto", syntax="proto3")
        original.dependency.append("discarded-go-option.proto")
        wire = original.SerializeToString()
        raw = (
            "var fileDescriptor_test = []byte{\n"
            + ",".join(f"0x{x:02x}" for x in gzip.compress(wire))
            + "\n}\n"
        ).encode()
        (tmp_path / (name + ".go")).write_bytes(raw)
        manifest["files"][name] = {
            "source": name + ".go",
            "go_sha256": hashlib.sha256(raw).hexdigest(),
            "original_descriptor_sha256": hashlib.sha256(wire).hexdigest(),
        }
        original.name = name + ".proto"
        original.ClearField("dependency")
        if name == "rpc":
            original.dependency.extend(["kv.proto", "auth.proto"])
        expected.file.append(original)
    result = expected.SerializeToString()
    manifest["descriptor_sha256"] = hashlib.sha256(result).hexdigest()
    if damage == "source":
        manifest["files"]["kv"]["go_sha256"] = "0" * 64
    elif damage == "wire":
        manifest["files"]["kv"]["original_descriptor_sha256"] = "0" * 64
    elif damage == "result":
        manifest["descriptor_sha256"] = "0" * 64
    vendor = tmp_path / "vendor/etcd"
    vendor.mkdir(parents=True)
    (vendor / "descriptor.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(G, "__file__", str(tmp_path / "generator.py"))
    destination = tmp_path / "result.desc"
    destination.write_bytes(b"previous reviewed artifact")
    if damage:
        with pytest.raises(ValueError, match="hash mismatch"):
            G.generate(tmp_path, destination)
        assert destination.read_bytes() == b"previous reviewed artifact"
    else:
        G.generate(tmp_path, destination)
        assert destination.read_bytes() == result


def test_cli_missing_source_does_not_publish(tmp_path, monkeypatch):
    destination = tmp_path / "result.desc"
    monkeypatch.setattr(
        sys, "argv", [str(SCRIPT), str(tmp_path / "absent"), "--output", str(destination)]
    )
    with pytest.raises(FileNotFoundError):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert not destination.exists()
