"""Opt-in tests of application-owned quota code, not a replacement load harness.

Set TOKENPLACE_QUOTA_SOURCE to a clean checkout of SOURCE; see the K243 guide.
No socket transport is used. Default repository CI skips this external dependency.
"""

import importlib.metadata
import os
import socket
import subprocess
from pathlib import Path

import pytest

SOURCE = "5e190f5c6ff66e9c05934a0e2ce2c1a440b9ea49"
SOURCE_PATH = os.environ.get("TOKENPLACE_QUOTA_SOURCE")
pytestmark = pytest.mark.skipif(not SOURCE_PATH, reason="requires pinned token.place checkout")


@pytest.fixture(scope="module")
def api_module(tmp_path_factory):
    source = Path(SOURCE_PATH).resolve()
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True)
    assert revision.strip() == SOURCE
    assert not subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=normal"], text=True
    ).strip()
    # dotenv inputs can be ignored by git; none belong in this offline fixture.
    assert not list(source.glob(".env*")) or all(
        p.name.endswith(".example") for p in source.glob(".env*")
    )
    for package, version in (("Flask", "3.1.2"), ("Flask-Limiter", "3.11.0"), ("limits", "5.8.0")):
        assert importlib.metadata.version(package) == version
    sandbox = tmp_path_factory.mktemp("quota")

    def no_network(*args, **kwargs):
        raise AssertionError("network is forbidden in quota fixtures")

    with pytest.MonkeyPatch.context() as patch:
        for key in list(os.environ):
            patch.delenv(key)
        for key in ("CONFIG", "DATA", "CACHE", "STATE"):
            patch.setenv(f"XDG_{key}_HOME", str(sandbox / key.lower()))
        patch.setenv("TOKENPLACE_RATE_LIMIT_STORAGE_URI", "memory://")
        patch.setenv("TOKENPLACE_RATE_LIMIT_TRUSTED_PROXIES", "")
        patch.setattr(socket.socket, "connect", no_network)
        patch.setattr(socket.socket, "connect_ex", no_network)
        patch.setattr(socket.socket, "sendto", no_network)
        patch.setattr(socket, "create_connection", no_network)
        patch.syspath_prepend(str(source))
        patch.chdir(sandbox)
        import api

        assert Path(api.__file__).resolve() == source / "api/__init__.py"
        yield api


@pytest.fixture
def app_factory(api_module, monkeypatch):
    from flask import Flask

    def make(hourly="2/hour", daily="1000/day"):
        monkeypatch.setenv("API_RATE_LIMIT", hourly)
        monkeypatch.setenv("API_DAILY_QUOTA", daily)
        app = Flask(__name__)
        limiter = api_module.init_app(app, metrics_instrumentation_enabled=False)
        # These are synthetic endpoints under the real middleware, not relay I/O.
        for status in (400, 404, 500):
            app.add_url_rule(
                f"/fixture-{status}",
                endpoint=f"fixture-{status}",
                view_func=lambda status=status: ("fixture", status),
            )
        for path in (
            "/",
            "/api/v1/meta",
            "/api/v1/version",
            "/healthz",
            "/livez",
            "/metrics",
            "/api/v1/relay/servers/next",
            "/api/v1/relay/responses/retrieve",
        ):
            if path not in {str(rule) for rule in app.url_map.iter_rules()}:
                app.add_url_rule(
                    path, endpoint=path, view_func=lambda: "fixture", methods=["GET", "POST"]
                )
        return app.test_client(), limiter

    return make


def counters(limiter):
    # Offline memory internals only: do not expose these through any HTTP endpoint.
    return dict(limiter._storage.storage)


def test_default_scope_is_client_and_endpoint_not_global(app_factory):
    client, limiter = app_factory()
    assert [client.get("/api/v1/models").status_code for _ in range(3)] == [200, 200, 429]
    # Same peer, distinct actual alias endpoint => separate default bucket.
    assert client.get("/v1/models").status_code == 200
    assert (
        client.get("/api/v1/models", environ_overrides={"REMOTE_ADDR": "192.0.2.2"}).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v1/models",
            headers={"CF-Connecting-IP": "192.0.2.3", "X-Forwarded-For": "192.0.2.3"},
        ).status_code
        == 429
    )
    assert len(counters(limiter)) == 6


@pytest.mark.parametrize("status", [400, 404, 500])
def test_retries_and_matched_errors_consume_attempts(app_factory, status):
    client, limiter = app_factory()
    assert [client.get(f"/fixture-{status}").status_code for _ in range(3)] == [status, status, 429]
    values = counters(limiter)
    assert sorted(values.values()) == [2, 3]


def test_429_hits_breached_hour_bucket_but_does_not_reach_daily_bucket(app_factory):
    client, limiter = app_factory()
    for _ in range(2):
        assert client.get("/api/v1/models").status_code == 200
    for _ in range(2):
        response = client.get("/api/v1/models")
        assert response.status_code == 429
        assert response.get_json()["error"]["code"] == "rate_limit_exceeded"
        assert int(response.headers["Retry-After"]) > 0
    values = counters(limiter)
    assert [v for k, v in values.items() if k.endswith("/hour")] == [4]
    assert [v for k, v in values.items() if k.endswith("/day")] == [2]


def test_daily_rejection_follows_hourly_accounting(app_factory):
    client, limiter = app_factory(hourly="60/hour", daily="1/day")
    assert [client.get("/api/v1/models").status_code for _ in range(2)] == [200, 429]
    assert sorted(counters(limiter).values()) == [2, 2]


def test_unmatched_404_does_not_hit_default_endpoint_buckets(app_factory):
    client, limiter = app_factory()
    for _ in range(4):
        assert client.get("/__k133_unmatched_probe__").status_code == 404
    assert counters(limiter) == {}


def test_exact_exemptions_do_not_consume_public_quota(app_factory):
    client, limiter = app_factory()
    for path in ("/", "/api/v1/meta", "/api/v1/version", "/healthz", "/livez", "/metrics"):
        for _ in range(3):
            assert client.get(path).status_code == 200
    for path in ("/api/v1/relay/servers/next", "/api/v1/relay/responses/retrieve"):
        for _ in range(3):
            assert client.post(path).status_code == 200
    for _ in range(3):
        assert client.options("/api/v1/models").status_code == 204
    assert counters(limiter) == {}
    assert [client.post("/api/v1/meta").status_code for _ in range(3)] == [200, 200, 429]


def test_fresh_memory_app_has_independent_counters(app_factory):
    first, _ = app_factory()
    assert [first.get("/api/v1/models").status_code for _ in range(3)] == [200, 200, 429]
    second, _ = app_factory()
    assert second.get("/api/v1/models").status_code == 200
    assert first.get("/api/v1/models").status_code == 429
