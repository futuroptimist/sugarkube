"""Offline checks for app runbook artifact-discovery links."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DSPACE_REPO = "https://github.com/democratizedspace/dspace"
TOKENPLACE_REPO = "https://github.com/futuroptimist/token.place"
DANIELSMITH_REPO = "https://github.com/futuroptimist/danielsmith.io"
DSPACE_GHCR_PACKAGE_LIST = (
    "https://github.com/orgs/democratizedspace/"
    "packages?repo_name=dspace"
)
BROKEN_DSPACE_CHART_PACKAGE_URL = (
    "https://github.com/orgs/democratizedspace/packages/"
    "container/package/charts%2Fdspace"
)

APP_LINKS = {
    "dspace": {
        "runbook": "docs/apps/dspace.md",
        "urls": [
            DSPACE_REPO,
            f"{DSPACE_REPO}/actions/workflows/ci-image.yml",
            f"{DSPACE_REPO}/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess",
            f"{DSPACE_REPO}/actions/workflows/ci-image.yml?query=branch%3Av3+is%3Asuccess",
            f"{DSPACE_REPO}/pkgs/container/dspace",
            f"{DSPACE_REPO}/actions/workflows/ci-helm.yml",
            DSPACE_GHCR_PACKAGE_LIST,
            f"{DSPACE_REPO}/blob/main/Dockerfile",
            f"{DSPACE_REPO}/tree/main/charts/dspace",
            f"{DSPACE_REPO}/blob/main/docs/ops/sugarkube-release.md",
        ],
    },
    "tokenplace": {
        "runbook": "docs/apps/tokenplace.md",
        "urls": [
            TOKENPLACE_REPO,
            f"{TOKENPLACE_REPO}/actions/workflows/ci-image.yml",
            f"{TOKENPLACE_REPO}/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess",
            f"{TOKENPLACE_REPO}/pkgs/container/tokenplace-relay",
            f"{TOKENPLACE_REPO}/actions/workflows/ci-helm.yml",
            f"{TOKENPLACE_REPO}/pkgs/container/charts%2Ftokenplace",
            f"{TOKENPLACE_REPO}/blob/main/Dockerfile",
            f"{TOKENPLACE_REPO}/tree/main/charts/tokenplace",
            f"{TOKENPLACE_REPO}/blob/main/docs/ops/sugarkube-release.md",
        ],
    },
    "danielsmith": {
        "runbook": "docs/apps/danielsmith.md",
        "urls": [
            DANIELSMITH_REPO,
            f"{DANIELSMITH_REPO}/actions/workflows/ci-image.yml",
            f"{DANIELSMITH_REPO}/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess",
            f"{DANIELSMITH_REPO}/pkgs/container/danielsmith.io",
            f"{DANIELSMITH_REPO}/actions/workflows/ci-helm.yml",
            f"{DANIELSMITH_REPO}/pkgs/container/charts%2Fdanielsmith",
            f"{DANIELSMITH_REPO}/blob/main/Dockerfile",
            f"{DANIELSMITH_REPO}/tree/main/charts/danielsmith",
            f"{DANIELSMITH_REPO}/blob/main/docs/ops/sugarkube-release.md",
        ],
    },
}

README_QUICK_LINKS = {
    "dspace": [
        "docs/apps/dspace.md",
        f"{DSPACE_REPO}/actions/workflows/ci-image.yml",
        f"{DSPACE_REPO}/pkgs/container/dspace",
        f"{DSPACE_REPO}/actions/workflows/ci-helm.yml",
        DSPACE_GHCR_PACKAGE_LIST,
    ],
    "tokenplace": [
        "docs/apps/tokenplace.md",
        f"{TOKENPLACE_REPO}/actions/workflows/ci-image.yml",
        f"{TOKENPLACE_REPO}/pkgs/container/tokenplace-relay",
        f"{TOKENPLACE_REPO}/actions/workflows/ci-helm.yml",
        f"{TOKENPLACE_REPO}/pkgs/container/charts%2Ftokenplace",
    ],
    "danielsmith": [
        "docs/apps/danielsmith.md",
        f"{DANIELSMITH_REPO}/actions/workflows/ci-image.yml",
        f"{DANIELSMITH_REPO}/pkgs/container/danielsmith.io",
        f"{DANIELSMITH_REPO}/actions/workflows/ci-helm.yml",
        f"{DANIELSMITH_REPO}/pkgs/container/charts%2Fdanielsmith",
    ],
}

REQUIRED_DISCOVERY_TERMS = [
    "app repository",
    "image workflow",
    "GHCR image package",
    "chart workflow",
    "GHCR chart package",
    "Dockerfile",
    "chart source path",
    "release guide",
]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_app_runbooks_include_artifact_link_matrix() -> None:
    for app, expected in APP_LINKS.items():
        text = _read(expected["runbook"])
        assert "### Artifact links" in text, f"{app} runbook needs an artifact links table"
        assert "Web UI shortcuts:" in text, f"{app} runbook needs image shortcuts"
        for url in expected["urls"]:
            assert url in text, f"{url} missing from {expected['runbook']}"


def test_readme_application_runbooks_include_quick_artifact_links() -> None:
    readme = _read("README.md")
    for app, urls in README_QUICK_LINKS.items():
        for url in urls:
            assert url in readme, f"README app runbooks section missing {app} link {url}"


def test_dspace_docs_do_not_link_missing_chart_package_page() -> None:
    for relative_path in ("docs/apps/dspace.md", "README.md"):
        text = _read(relative_path)
        assert BROKEN_DSPACE_CHART_PACKAGE_URL not in text
        assert "chart package page pending" in text or "No public package page" in text


def test_contract_and_onboarding_require_artifact_discovery_links() -> None:
    contract = _read("docs/app_deployment_contract.md")
    onboarding = _read("docs/app_onboarding.md")
    combined = f"{contract}\n{onboarding}"
    assert "Artifact discovery links" in contract
    for term in REQUIRED_DISCOVERY_TERMS:
        assert term in combined, f"artifact discovery checklist missing {term!r}"
