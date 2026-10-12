"""Synthetic offline contract tests; no charts or cluster prerequisites."""

import ast
import builtins
import contextlib
import copy
import importlib.util
import io
import json
import os
import socket
import subprocess
import sys
import unittest
import urllib.request
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "chart_lock_contract", ROOT / "scripts/chart_lock_contract.py"
)
c = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = c
SPEC.loader.exec_module(c)
FIXTURES = ROOT / "tests/fixtures/chart_locks"


def encode(record):
    return (json.dumps(record, separators=(",", ":")) + "\n").encode()


def expected_for(lock, request):
    fields = {
        key: value
        for key, value in request.items()
        if key not in ("schema_version", "policy_version")
    }
    fields["artifact_ids"] = tuple(fields["artifact_ids"])
    fields["package_urls"] = tuple((a["artifact_id"], a["package_url"]) for a in lock["artifacts"])
    return c.ExpectedOperation(**fields)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.lock_raw = (FIXTURES / "lock.json").read_bytes()
        self.review_raw = (FIXTURES / "content-review.json").read_bytes()
        self.request_raw = (FIXTURES / "operation-request.json").read_bytes()
        self.lock = json.loads(self.lock_raw)
        self.review = json.loads(self.review_raw)
        self.request = json.loads(self.request_raw)
        self.expected = expected_for(self.lock, self.request)

    def refuse(self, code, function, *args, **kwargs):
        with self.assertRaises(c.Refusal) as caught:
            function(*args, **kwargs)
        self.assertEqual(str(caught.exception), code)
        self.assertEqual(caught.exception.args, (code,))

    def validate(self, lock=None, reviews=None, request=None, expected=None):
        return c.validate_records(
            self.lock_raw if lock is None else lock,
            [self.review_raw] if reviews is None else reviews,
            self.request_raw if request is None else request,
            expected=self.expected if expected is None else expected,
        )

    def bundle(self, count=1):
        lock = copy.deepcopy(self.lock)
        lock["artifacts"] = []
        reviews = []
        for index in range(count):
            review = dict(self.review, review_id=f"review-{index}", artifact_id=f"chart-{index}")
            raw = encode(review)
            reviews.append(raw)
            artifact = dict(
                self.lock["artifacts"][0],
                artifact_id=review["artifact_id"],
                review_id=review["review_id"],
                review_sha256=c.sha256(raw),
            )
            lock["artifacts"].append(artifact)
        request = dict(
            self.request,
            lock_sha256=c.sha256(encode(lock)),
            artifact_ids=[a["artifact_id"] for a in lock["artifacts"]],
        )
        return lock, reviews, request

    def check_bundle(self, lock, reviews, request):
        request = dict(request, lock_sha256=c.sha256(encode(lock)))
        return self.validate(encode(lock), reviews, encode(request), expected_for(lock, request))

    def test_original_fixture_bytes_and_no_authority(self):
        result = self.validate()
        self.assertEqual(result.lock, self.lock)
        self.assertEqual(result.reviews, (self.review,))
        self.assertEqual(result.request, self.request)
        self.assertEqual(result.lock_sha256, c.sha256(self.lock_raw))
        self.assertEqual(result.review_sha256s, (c.sha256(self.review_raw),))
        self.assertFalse(hasattr(result, "approved"))
        self.assertFalse(hasattr(result, "execute"))
        self.assertFalse(hasattr(result, "admit"))

    def test_exact_lock_bytes_include_whitespace(self):
        changed = self.lock_raw + b" "
        self.assertNotEqual(c.sha256(changed), c.sha256(self.lock_raw))
        self.refuse("DIGEST_MISMATCH", self.validate, lock=changed)
        request = dict(self.request, lock_sha256=c.sha256(changed))
        self.refuse("EXPECTATION_MISMATCH", self.validate, lock=changed, request=encode(request))
        self.validate(changed, request=encode(request), expected=expected_for(self.lock, request))

    def test_exact_review_bytes_include_whitespace(self):
        self.refuse("DIGEST_MISMATCH", self.validate, reviews=[self.review_raw + b" "])
        self.refuse("DIGEST_MISMATCH", self.validate, reviews=[encode(self.review)])

    def test_record_size_boundary(self):
        at_limit = b"{}" + b" " * (c.MAX_RECORD_BYTES - 2)
        self.assertEqual(c.decode_record(at_limit), {})
        self.refuse("RECORD_SIZE", c.decode_record, at_limit + b" ")
        self.refuse("RECORD_SIZE", c.decode_record, b"\xff" * (c.MAX_RECORD_BYTES + 1))
        self.refuse("INVALID_TYPE", c.decode_record, bytearray(b"{}"))
        self.refuse("INVALID_TYPE", c.decode_record, "{}")

    def test_depth_is_checked_before_object_construction(self):
        at_limit = b'{"a":' * 32 + b"0" + b"}" * 32
        self.assertIsInstance(c.decode_record(at_limit), dict)
        with patch.object(c.json, "loads", side_effect=AssertionError("decoded too early")):
            self.refuse("RECORD_DEPTH", c.decode_record, b'{"a":' * 33 + b"0" + b"}" * 33)
        self.assertEqual(c.decode_record(b'{"a":"[{}]\\"\\\\"}'), {"a": '[{}]"\\'})

    def test_strict_json_refusals(self):
        cases = [
            (b'{"a":1,"a":2}', "DUPLICATE_KEY"),
            (b'{"a":1,"\\u0061":2}', "DUPLICATE_KEY"),
            (b'{"a":{"x":1,"x":2}}', "DUPLICATE_KEY"),
            (b'{"x":NaN}', "INVALID_NUMBER"),
            (b'{"x":Infinity}', "INVALID_NUMBER"),
            (b'{"x":-Infinity}', "INVALID_NUMBER"),
            (b'{"x":1e999}', "INVALID_NUMBER"),
            (b'{"x":1.0}', "INVALID_NUMBER"),
            (b'{"x":' + b"9" * 100 + b"}", "INVALID_NUMBER"),
            (b"\xff", "INVALID_ENCODING"),
            (b"\xef\xbb\xbf{}", "INVALID_ENCODING"),
            (b'{"x":"\\ud800"}', "INVALID_TEXT"),
            (b'{"x":"\\u0085"}', "INVALID_TEXT"),
            (b'{"x":"\\u2028"}', "INVALID_TEXT"),
            (b'{"x":"\\n"}', "INVALID_TEXT"),
            (b'{"\\r":1}', "INVALID_TEXT"),
            (b'{"x":1,}', "INVALID_JSON"),
            (b"{}{}", "INVALID_JSON"),
            (b"[1]", "INVALID_TYPE"),
            (b"null", "INVALID_TYPE"),
            (b'{"x":01}', "INVALID_JSON"),
            (b'{"x":', "INVALID_JSON"),
        ]
        for raw, code in cases:
            with self.subTest(raw=raw):
                self.refuse(code, c.decode_record, raw)

    def test_every_required_field_and_unknown_field(self):
        records = [
            (self.lock, c.validate_lock),
            (self.review, c.validate_review),
            (self.request, c.validate_request),
        ]
        for record, validate in records:
            for field in record:
                with self.subTest(role=validate.__name__, field=field):
                    missing = dict(record)
                    del missing[field]
                    self.refuse("INVALID_FIELDS", validate, encode(missing))
            self.refuse("INVALID_FIELDS", validate, encode(dict(record, approved=True)))
        artifact = self.lock["artifacts"][0]
        for field in artifact:
            lock = copy.deepcopy(self.lock)
            del lock["artifacts"][0][field]
            self.refuse("INVALID_FIELDS", c.validate_lock, encode(lock))

    def test_boolean_versions_and_unknown_versions(self):
        for record, validate in [
            (self.lock, c.validate_lock),
            (self.review, c.validate_review),
            (self.request, c.validate_request),
        ]:
            for field in ("schema_version", "policy_version"):
                if field not in record:
                    continue
                for value, code in [
                    (True, "INVALID_TYPE"),
                    ("1", "INVALID_TYPE"),
                    (2, "UNSUPPORTED_VERSION"),
                    (0, "UNSUPPORTED_VERSION"),
                ]:
                    self.refuse(code, validate, encode(dict(record, **{field: value})))

    def test_artifact_types_and_coordinates(self):
        cases = [
            ("archive_size_bytes", True, "INVALID_TYPE"),
            ("archive_size_bytes", 0, "INVALID_SIZE"),
            ("archive_size_bytes", -1, "INVALID_SIZE"),
            ("archive_size_bytes", 2**63, "INVALID_SIZE"),
            ("archive_size_bytes", "1", "INVALID_TYPE"),
            ("archive_sha256", "A" * 64, "INVALID_COORDINATE"),
            ("review_sha256", "a" * 63, "INVALID_COORDINATE"),
            ("artifact_id", "../chart", "INVALID_COORDINATE"),
            ("artifact_id", [], "INVALID_TYPE"),
            ("chart_name", "chart/name", "INVALID_COORDINATE"),
            ("chart_version", "01.2.3", "INVALID_COORDINATE"),
            ("chart_version", "1.2.3-01", "INVALID_COORDINATE"),
            ("chart_version", "latest", "INVALID_COORDINATE"),
            ("review_id", "", "INVALID_TEXT"),
        ]
        for field, value, code in cases:
            with self.subTest(field=field, value=value):
                lock = copy.deepcopy(self.lock)
                lock["artifacts"][0][field] = value
                self.refuse(code, c.validate_lock, encode(lock))
        lock = copy.deepcopy(self.lock)
        lock["artifacts"][0]["archive_size_bytes"] = 2**63 - 1
        lock["artifacts"][0]["chart_version"] = "1.2.3-rc.1+build.001"
        c.validate_lock(encode(lock))

    def test_url_refusals(self):
        urls = [
            "http://example.invalid/a",
            "https:///a",
            "https://user@example.invalid/a",
            "https://example.invalid/a?",
            "https://example.invalid/a#",
            "https://example.invalid/a?x=y",
            "https://example.invalid/a#x",
            "https://example.invalid/a b",
            "https://example.invalid/a\\b",
            "https://example.invalid/a%0a",
            "https://example.invalid/a%7F",
            "https://example.invalid/a%xy",
            "https://example.invalid:0/a",
            "https://example.invalid:65536/a",
            "https://example.invalid:/a",
            "https://-bad.invalid/a",
            "https://example..invalid/a",
            "https://[broken/a",
        ]
        for url in urls:
            with self.subTest(url=url):
                lock = copy.deepcopy(self.lock)
                lock["artifacts"][0]["package_url"] = url
                self.refuse("INVALID_URL", c.validate_lock, encode(lock))
        self.refuse(
            "URL_MISMATCH",
            self.validate,
            expected=replace(
                self.expected,
                package_urls=(
                    ("synthetic-chart", "https://EXAMPLE.invalid/synthetic-chart-1.2.3.tgz"),
                ),
            ),
        )

    def test_artifact_count_and_duplicate_identifiers(self):
        lock, reviews, request = self.bundle(16)
        self.check_bundle(lock, reviews, request)
        lock, reviews, request = self.bundle(17)
        self.refuse("INVALID_COUNT", c.validate_lock, encode(lock))
        self.refuse("INVALID_COUNT", self.validate, reviews=reviews)
        self.refuse("INVALID_COUNT", c.validate_request, encode(request))
        self.refuse("INVALID_COUNT", c.validate_lock, encode(dict(self.lock, artifacts=[])))
        self.refuse("INVALID_COUNT", self.validate, reviews=[])
        for field in ("artifact_id", "review_id"):
            lock, _, _ = self.bundle(2)
            lock["artifacts"][1][field] = lock["artifacts"][0][field]
            self.refuse("DUPLICATE_ID", c.validate_lock, encode(lock))
        self.refuse("DUPLICATE_ID", self.validate, reviews=[self.review_raw, self.review_raw])
        self.refuse("INVALID_TYPE", self.validate, reviews=iter([self.review_raw]))

    def test_review_identity_and_digest_mismatches(self):
        for field, value in [
            ("artifact_id", "other"),
            ("chart_name", "other"),
            ("chart_version", "9.9.9"),
            ("archive_sha256", "0" * 64),
        ]:
            review = dict(self.review, **{field: value})
            raw = encode(review)
            lock = copy.deepcopy(self.lock)
            lock["artifacts"][0]["review_sha256"] = c.sha256(raw)
            self.refuse("IDENTITY_MISMATCH", self.check_bundle, lock, [raw], self.request)
        extra = encode(dict(self.review, review_id="unreferenced"))
        self.refuse("REVIEW_SET", self.validate, reviews=[extra])
        self.refuse("REVIEW_SET", self.validate, reviews=[self.review_raw, extra])

    def test_expectation_substitutions(self):
        substitutions = dict(
            repository="other/repository",
            repository_revision="2" * 40,
            lock_sha256="0" * 64,
            artifact_ids=("other",),
            environment="prod",
            action="install",
            namespace="other",
            release="other",
            operation_id="other",
            phase="pre-mutation",
        )
        for field, value in substitutions.items():
            with self.subTest(field=field):
                self.refuse(
                    "EXPECTATION_MISMATCH",
                    self.validate,
                    expected=replace(self.expected, **{field: value}),
                )
        for field, value in [
            ("environment", "production"),
            ("action", "delete"),
            ("phase", "approved"),
        ]:
            self.refuse(
                "INVALID_ENUM", c.validate_request, encode(dict(self.request, **{field: value}))
            )
        for field, value in [
            ("repository", "../repo"),
            ("repository_revision", "main"),
            ("namespace", "bad/name"),
        ]:
            self.refuse(
                "INVALID_COORDINATE",
                c.validate_request,
                encode(dict(self.request, **{field: value})),
            )
        self.refuse("INVALID_EXPECTATION", self.validate, expected={})
        self.refuse(
            "INVALID_EXPECTATION",
            self.validate,
            expected=replace(self.expected, package_urls=self.expected.package_urls * 2),
        )

    def test_expected_coordinates_cannot_invoke_custom_equality(self):
        class UnexpectedComparison:
            def __eq__(self, other):
                raise AssertionError("custom comparison invoked")

        value = UnexpectedComparison()
        for changed in (
            {"repository": value},
            {"artifact_ids": ("synthetic-chart",) * 17},
            {"package_urls": self.expected.package_urls * 17},
            {"artifact_ids": (value,)},
            {"frozen_input_manifest_sha256": value},
            {"package_urls": ((value, "https://example.invalid/a"),)},
        ):
            self.refuse(
                "INVALID_EXPECTATION",
                self.validate,
                expected=replace(self.expected, **changed),
            )

    def test_record_boundaries_apply_to_each_role(self):
        for raw, validate in (
            (self.lock_raw, c.validate_lock),
            (self.review_raw, c.validate_review),
            (self.request_raw, c.validate_request),
        ):
            padded = raw + b" " * (c.MAX_RECORD_BYTES - len(raw))
            validate(padded)
            self.refuse("RECORD_SIZE", validate, padded + b" ")
        raw = b'{"a":' * 33 + b"0" + b"}" * 33
        for validate in (c.validate_lock, c.validate_review, c.validate_request):
            self.refuse("RECORD_DEPTH", validate, raw)

    def test_review_order_and_selected_order(self):
        lock, reviews, request = self.bundle(2)
        self.check_bundle(lock, list(reversed(reviews)), request)
        expected = expected_for(lock, request)
        request["artifact_ids"].reverse()
        self.refuse(
            "EXPECTATION_MISMATCH",
            self.validate,
            encode(lock),
            reviews,
            encode(request),
            expected,
        )

    def test_unknown_selection_and_duplicate_selection(self):
        request = dict(self.request, artifact_ids=["missing"])
        self.refuse(
            "UNKNOWN_ARTIFACT",
            self.validate,
            request=encode(request),
            expected=expected_for(self.lock, request),
        )
        request = dict(self.request, artifact_ids=["synthetic-chart"] * 2)
        self.refuse("DUPLICATE_ID", c.validate_request, encode(request))

    def test_dependency_graph_and_review_eligibility(self):
        for changed, code in [
            ({"dependencies": ["missing"]}, "UNKNOWN_ARTIFACT"),
            ({"dependencies": ["synthetic-chart"]}, "DEPENDENCY_CYCLE"),
            ({"environments": ["prod"]}, "ENVIRONMENT_MISMATCH"),
            ({"outcome": "rejected"}, "REVIEW_NOT_ACCEPTED"),
        ]:
            raw = encode(dict(self.review, **changed))
            lock = copy.deepcopy(self.lock)
            lock["artifacts"][0]["review_sha256"] = c.sha256(raw)
            self.refuse(code, self.check_bundle, lock, [raw], self.request)
        lock, reviews, request = self.bundle(2)
        review = json.loads(reviews[0])
        reviews[0] = encode(dict(review, dependencies=["chart-1"]))
        lock["artifacts"][0]["review_sha256"] = c.sha256(reviews[0])
        self.check_bundle(lock, reviews, request)
        request["artifact_ids"] = ["chart-0"]
        self.refuse("UNSELECTED_DEPENDENCY", self.check_bundle, lock, reviews, request)
        request["artifact_ids"] = ["chart-0", "chart-1"]
        review = json.loads(reviews[1])
        reviews[1] = encode(dict(review, dependencies=["chart-0"]))
        lock["artifacts"][1]["review_sha256"] = c.sha256(reviews[1])
        self.refuse("DEPENDENCY_CYCLE", self.check_bundle, lock, reviews, request)

    def test_review_fields(self):
        for field, value, code in [
            ("reviewer", "forged\naccepted", "INVALID_TEXT"),
            ("evidence_kind", "signed", "INVALID_ENUM"),
            ("evidence_references", [], "INVALID_COUNT"),
            ("dependencies", ["one", "one"], "DUPLICATE_ID"),
            ("environments", ["production"], "INVALID_ENUM"),
            ("outcome", True, "INVALID_TYPE"),
        ]:
            self.refuse(code, c.validate_review, encode(dict(self.review, **{field: value})))
        c.validate_review(encode(dict(self.review, evidence_kind="publisher-authenticated")))

    def test_pre_mutation_requires_both_bound_digests(self):
        raw = (FIXTURES / "pre-mutation-request.json").read_bytes()
        request = json.loads(raw)
        expected = expected_for(self.lock, request)
        self.validate(request=raw, expected=expected)
        for field in ("frozen_input_manifest_sha256", "validated_output_sha256"):
            missing = dict(request)
            del missing[field]
            self.refuse("INVALID_FIELDS", c.validate_request, encode(missing))
            self.refuse(
                "EXPECTATION_MISMATCH",
                self.validate,
                request=raw,
                expected=replace(expected, **{field: "0" * 64}),
            )
            self.refuse(
                "INVALID_FIELDS",
                c.validate_request,
                encode(dict(self.request, **{field: "0" * 64})),
            )
        self.refuse(
            "INVALID_EXPECTATION",
            self.validate,
            expected=replace(self.expected, frozen_input_manifest_sha256="0" * 64),
        )

    def test_import_and_validation_have_no_io_or_output(self):
        source = (ROOT / "scripts/chart_lock_contract.py").read_text()
        compiled = compile(source, "chart_lock_contract.py", "exec")
        tree = ast.parse(source)
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        self.assertEqual(imports, {"hashlib", "json", "re", "dataclasses", "urllib.parse"})
        output = io.StringIO()
        blocked = AssertionError("unexpected side effect")
        with contextlib.ExitStack() as stack:
            for owner, name in (
                (builtins, "open"),
                (io, "open"),
                (os, "open"),
                (os, "system"),
                (subprocess, "Popen"),
                (socket, "socket"),
                (urllib.request, "urlopen"),
            ):
                stack.enter_context(patch.object(owner, name, side_effect=blocked))
            stack.enter_context(contextlib.redirect_stdout(output))
            stack.enter_context(contextlib.redirect_stderr(output))
            namespace = {"__name__": c.__name__}
            exec(compiled, namespace)
            result = namespace["validate_records"](
                self.lock_raw,
                [self.review_raw],
                self.request_raw,
                expected=namespace["ExpectedOperation"](**vars(self.expected)),
            )
            self.assertEqual(result.lock_sha256, self.request["lock_sha256"])
            self.validate()
            self.refuse(
                "INVALID_FIELDS", self.validate, request=encode(dict(self.request, approved=True))
            )
        self.assertEqual(output.getvalue(), "")

    def test_schemas_document_exact_field_sets(self):
        folder = ROOT / "config/chart-locks"
        lock_schema = json.loads((folder / "lock.schema.json").read_bytes())
        review_schema = json.loads((folder / "content-review.schema.json").read_bytes())
        request_schema = json.loads((folder / "operation-request.schema.json").read_bytes())
        mutation = json.loads((FIXTURES / "pre-mutation-request.json").read_bytes())
        for record, schema in [
            (self.lock, lock_schema),
            (self.review, review_schema),
            (self.request, request_schema["oneOf"][0]),
            (mutation, request_schema["oneOf"][1]),
        ]:
            self.assertEqual(set(record), set(schema["required"]))
            self.assertEqual(set(record), set(schema["properties"]))
            self.assertFalse(schema["additionalProperties"])
        self.assertEqual(lock_schema["properties"]["artifacts"]["maxItems"], 16)


if __name__ == "__main__":
    unittest.main()
