"""Offline checks for application runbook artifact-discovery links."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

APP_LINKS = {
    "dspace": {
        "runbook": "docs/apps/dspace.md",
        "readme_label": "DSPACE",
        "urls": (
            "https://github.com/democratizedspace/dspace",
            "https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml",
            ("https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml"
             "?query=branch%3Amain+is%3Asuccess"),
            "https://github.com/democratizedspace/dspace/pkgs/container/dspace",
            "https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml",
            ("https://github.com/orgs/democratizedspace/packages"
             "?repo_name=dspace&q=charts%2Fdspace"),
            "https://github.com/democratizedspace/dspace/blob/main/Dockerfile",
            "https://github.com/democratizedspace/dspace/tree/main/charts/dspace",
            ("https://github.com/democratizedspace/dspace/blob/main/docs/ops"
             "/sugarkube-release.md"),
        ),
    },
    "tokenplace": {
        "runbook": "docs/apps/tokenplace.md",
        "readme_label": "token.place",
        "urls": (
            "https://github.com/futuroptimist/token.place",
            "https://github.com/futuroptimist/token.place/actions/workflows/ci-image.yml",
            ("https://github.com/futuroptimist/token.place/actions/workflows/ci-image.yml"
             "?query=branch%3Amain+is%3Asuccess"),
            "https://github.com/futuroptimist/token.place/pkgs/container/tokenplace-relay",
            "https://github.com/futuroptimist/token.place/actions/workflows/ci-helm.yml",
            "https://github.com/futuroptimist/token.place/pkgs/container/charts%2Ftokenplace",
            "https://github.com/futuroptimist/token.place/blob/main/Dockerfile",
            "https://github.com/futuroptimist/token.place/tree/main/charts/tokenplace",
            "https://github.com/futuroptimist/token.place/blob/main/docs/ops/sugarkube-release.md",
        ),
    },
    "danielsmith": {
        "runbook": "docs/apps/danielsmith.md",
        "readme_label": "danielsmith.io",
        "urls": (
            "https://github.com/futuroptimist/danielsmith.io",
            "https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-image.yml",
            ("https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-image.yml"
             "?query=branch%3Amain+is%3Asuccess"),
            "https://github.com/futuroptimist/danielsmith.io/pkgs/container/danielsmith.io",
            "https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-helm.yml",
            "https://github.com/futuroptimist/danielsmith.io/pkgs/container/charts%2Fdanielsmith",
            "https://github.com/futuroptimist/danielsmith.io/blob/main/Dockerfile",
            "https://github.com/futuroptimist/danielsmith.io/tree/main/charts/danielsmith",
            ("https://github.com/futuroptimist/danielsmith.io/blob/main/docs/ops"
             "/sugarkube-release.md"),
        ),
    },
}

README_ARTIFACT_URLS = {
    app: tuple(
        url
        for url in data["urls"]
        if (
            ("actions/workflows" in url and "?query=" not in url)
            or "pkgs/container" in url
            or "packages?" in url
        )
    )
    for app, data in APP_LINKS.items()
}

REQUIRED_CHECKLIST_TERMS = (
    "app repository",
    "image workflow",
    "GHCR image package",
    "chart workflow",
    "GHCR chart package",
    "Dockerfile",
    "chart source path",
    "app-repo Sugarkube release guide",
)


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_app_runbooks_include_artifact_discovery_urls() -> None:
    for app, data in APP_LINKS.items():
        text = _read(data["runbook"])
        assert "### Artifact links" in text, f"{app} runbook should expose an artifact links table."
        for url in data["urls"]:
            assert url in text, f"{app} runbook is missing {url}."


def test_readme_application_runbooks_include_quick_artifact_links() -> None:
    readme = _read("README.md")
    for app, data in APP_LINKS.items():
        assert data["readme_label"] in readme, f"README should list {app}."
        for url in README_ARTIFACT_URLS[app]:
            assert url in readme, f"README app runbooks section is missing {url}."


def test_shared_docs_require_artifact_discovery_link_checklist() -> None:
    contract = _read("docs/app_deployment_contract.md")
    onboarding = _read("docs/app_onboarding.md")
    combined = contract + "\n" + onboarding

    assert "Required runbook links" in contract
    for term in REQUIRED_CHECKLIST_TERMS:
        assert term in combined, f"Shared app docs should require {term}."
