from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DSPACE_REPO = "https://github.com/democratizedspace/dspace"
TOKENPLACE_REPO = "https://github.com/futuroptimist/token.place"
DANIELSMITH_REPO = "https://github.com/futuroptimist/danielsmith.io"

APP_LINKS = {
    "dspace": {
        "runbook": "docs/apps/dspace.md",
        "readme_label": "DSPACE",
        "urls": {
            "app_repo": DSPACE_REPO,
            "image_workflow": f"{DSPACE_REPO}/actions/workflows/ci-image.yml",
            "successful_main_images": (
                f"{DSPACE_REPO}/actions/workflows/ci-image.yml"
                "?query=branch%3Amain+is%3Asuccess"
            ),
            "successful_v3_images": (
                f"{DSPACE_REPO}/actions/workflows/ci-image.yml"
                "?query=branch%3Av3+is%3Asuccess"
            ),
            "image_package": f"{DSPACE_REPO}/pkgs/container/dspace",
            "chart_workflow": f"{DSPACE_REPO}/actions/workflows/ci-helm.yml",
            "chart_package": (
                "https://github.com/orgs/democratizedspace/packages"
                "?repo_name=dspace&ecosystem=container"
            ),
            "dockerfile": f"{DSPACE_REPO}/blob/main/Dockerfile",
            "chart_source": f"{DSPACE_REPO}/tree/main/charts/dspace",
            "release_guide": f"{DSPACE_REPO}/blob/main/docs/ops/sugarkube-release.md",
        },
    },
    "tokenplace": {
        "runbook": "docs/apps/tokenplace.md",
        "readme_label": "token.place",
        "urls": {
            "app_repo": TOKENPLACE_REPO,
            "image_workflow": f"{TOKENPLACE_REPO}/actions/workflows/ci-image.yml",
            "successful_main_images": (
                f"{TOKENPLACE_REPO}/actions/workflows/ci-image.yml"
                "?query=branch%3Amain+is%3Asuccess"
            ),
            "image_package": f"{TOKENPLACE_REPO}/pkgs/container/tokenplace-relay",
            "chart_workflow": f"{TOKENPLACE_REPO}/actions/workflows/ci-helm.yml",
            "chart_package": f"{TOKENPLACE_REPO}/pkgs/container/charts%2Ftokenplace",
            "dockerfile": f"{TOKENPLACE_REPO}/blob/main/Dockerfile",
            "chart_source": f"{TOKENPLACE_REPO}/tree/main/charts/tokenplace",
            "release_guide": f"{TOKENPLACE_REPO}/blob/main/docs/ops/sugarkube-release.md",
        },
    },
    "danielsmith": {
        "runbook": "docs/apps/danielsmith.md",
        "readme_label": "danielsmith.io",
        "urls": {
            "app_repo": DANIELSMITH_REPO,
            "image_workflow": f"{DANIELSMITH_REPO}/actions/workflows/ci-image.yml",
            "successful_main_images": (
                f"{DANIELSMITH_REPO}/actions/workflows/ci-image.yml"
                "?query=branch%3Amain+is%3Asuccess"
            ),
            "image_package": f"{DANIELSMITH_REPO}/pkgs/container/danielsmith.io",
            "chart_workflow": f"{DANIELSMITH_REPO}/actions/workflows/ci-helm.yml",
            "chart_package": f"{DANIELSMITH_REPO}/pkgs/container/charts%2Fdanielsmith",
            "dockerfile": f"{DANIELSMITH_REPO}/blob/main/Dockerfile",
            "chart_source": f"{DANIELSMITH_REPO}/tree/main/charts/danielsmith",
            "release_guide": f"{DANIELSMITH_REPO}/blob/main/docs/ops/sugarkube-release.md",
        },
    },
}

README_LINK_KEYS = {"image_workflow", "image_package", "chart_workflow", "chart_package"}


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text()


def test_app_runbooks_expose_artifact_discovery_links() -> None:
    for app in APP_LINKS.values():
        runbook = read(app["runbook"])
        assert "### Artifact links" in runbook
        assert "Web UI shortcuts" in runbook
        for name, url in app["urls"].items():
            assert url in runbook, f"{app['runbook']} is missing {name}: {url}"


def test_readme_exposes_quick_artifact_links_for_each_app() -> None:
    readme = read("README.md")
    for app in APP_LINKS.values():
        assert app["readme_label"] in readme
        for key in README_LINK_KEYS:
            assert app["urls"][key] in readme, (
                f"README.md is missing {key} for {app['readme_label']}"
            )


def test_shared_docs_require_artifact_discovery_checklist() -> None:
    contract = read("docs/app_deployment_contract.md")
    onboarding = read("docs/app_onboarding.md")
    required_phrases = [
        "Artifact discovery links",
        "app repo",
        "image workflow",
        "GHCR image package",
        "chart workflow",
        "GHCR chart package",
        "Dockerfile",
        "chart source path",
        "release guide",
    ]
    for phrase in required_phrases:
        assert phrase in contract or phrase in onboarding
