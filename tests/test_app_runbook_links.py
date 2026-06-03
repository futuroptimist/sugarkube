"""Offline regression checks for app runbook artifact discovery links."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

APP_LINKS = {
    "dspace": {
        "runbook": REPO_ROOT / "docs" / "apps" / "dspace.md",
        "readme_label": "DSPACE runbook",
        "urls": [
            "https://github.com/democratizedspace/dspace",
            "https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml",
            "https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess",
            "https://github.com/democratizedspace/dspace/actions/workflows/ci-image.yml?query=branch%3Av3+is%3Asuccess",
            "https://github.com/democratizedspace/dspace/pkgs/container/dspace",
            "https://github.com/democratizedspace/dspace/actions/workflows/ci-helm.yml",
            "https://github.com/orgs/democratizedspace/packages?ecosystem=container&repo_name=dspace",
            "https://github.com/democratizedspace/dspace/blob/main/Dockerfile",
            "https://github.com/democratizedspace/dspace/tree/main/charts/dspace",
            "https://github.com/democratizedspace/dspace/blob/main/docs/ops/sugarkube-release.md",
        ],
    },
    "tokenplace": {
        "runbook": REPO_ROOT / "docs" / "apps" / "tokenplace.md",
        "readme_label": "token.place runbook",
        "urls": [
            "https://github.com/futuroptimist/token.place",
            "https://github.com/futuroptimist/token.place/actions/workflows/ci-image.yml",
            "https://github.com/futuroptimist/token.place/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess",
            "https://github.com/futuroptimist/token.place/pkgs/container/tokenplace-relay",
            "https://github.com/futuroptimist/token.place/actions/workflows/ci-helm.yml",
            "https://github.com/futuroptimist/token.place/pkgs/container/charts%2Ftokenplace",
            "https://github.com/futuroptimist/token.place/blob/main/Dockerfile",
            "https://github.com/futuroptimist/token.place/tree/main/charts/tokenplace",
            "https://github.com/futuroptimist/token.place/blob/main/docs/ops/sugarkube-release.md",
        ],
    },
    "danielsmith": {
        "runbook": REPO_ROOT / "docs" / "apps" / "danielsmith.md",
        "readme_label": "danielsmith.io runbook",
        "urls": [
            "https://github.com/futuroptimist/danielsmith.io",
            "https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-image.yml",
            "https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-image.yml?query=branch%3Amain+is%3Asuccess",
            "https://github.com/futuroptimist/danielsmith.io/pkgs/container/danielsmith.io",
            "https://github.com/futuroptimist/danielsmith.io/actions/workflows/ci-helm.yml",
            "https://github.com/futuroptimist/danielsmith.io/pkgs/container/charts%2Fdanielsmith",
            "https://github.com/futuroptimist/danielsmith.io/blob/main/Dockerfile",
            "https://github.com/futuroptimist/danielsmith.io/tree/main/charts/danielsmith",
            "https://github.com/futuroptimist/danielsmith.io/blob/main/docs/ops/sugarkube-release.md",
        ],
    },
}

README_REQUIRED_URLS = {
    app: [
        url
        for url in metadata["urls"]
        if ("/actions/workflows/" in url and "?query=" not in url) or "/pkgs/container/" in url or "packages?" in url
    ]
    for app, metadata in APP_LINKS.items()
}

REQUIRED_CHECKLIST_TERMS = [
    "app repository",
    "image workflow",
    "GHCR image package",
    "chart publish workflow",
    "GHCR chart package",
    "Dockerfile or source image build path",
    "chart source path",
    "app-repo Sugarkube release guide",
]


def test_app_runbooks_include_artifact_discovery_links() -> None:
    for app, metadata in APP_LINKS.items():
        text = metadata["runbook"].read_text(encoding="utf-8")
        assert "### Artifact links" in text, f"{app} runbook should expose artifact links"
        for url in metadata["urls"]:
            assert url in text, f"{app} runbook is missing {url}"


def test_readme_application_runbooks_include_artifact_shortcuts() -> None:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for app, metadata in APP_LINKS.items():
        assert metadata["readme_label"] in text, f"README should link the {app} runbook"
        for url in README_REQUIRED_URLS[app]:
            assert url in text, f"README is missing {app} artifact shortcut {url}"


def test_shared_docs_require_future_artifact_discovery_links() -> None:
    contract = (REPO_ROOT / "docs" / "app_deployment_contract.md").read_text(encoding="utf-8")
    onboarding = (REPO_ROOT / "docs" / "app_onboarding.md").read_text(encoding="utf-8")
    combined = f"{contract}\n{onboarding}"
    for term in REQUIRED_CHECKLIST_TERMS:
        assert term in combined, f"shared docs should require {term} links"
    assert "Image workflow URL" in onboarding
    assert "GHCR chart package URL" in onboarding
