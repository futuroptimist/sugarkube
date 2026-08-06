#!/usr/bin/env python3
"""Generate bounded DSPACE Prometheus rules from a finalized release record."""

import argparse
import json
from pathlib import Path

RUNBOOK = "https://github.com/futuroptimist/sugarkube/blob/main/docs/observability-dspace-release-integrity.md"


def generate(evidence: dict) -> dict:
    required = {"recordType": "final", "app": "dspace", "environment": "staging"}
    if any(evidence.get(k) != v for k, v in required.items()):
        raise ValueError("only finalized staging DSPACE evidence is accepted")
    revision = evidence["sourceRevision"]
    tag = evidence["imageTag"]
    digest = evidence["imageDigest"]
    if len(revision) != 40 or not tag.startswith("main-") or not digest.startswith("sha256:"):
        raise ValueError("evidence lacks immutable release coordinates")
    labels = {
        "application": "dspace",
        "environment": "staging",
        "cluster": "sugarkube-int",
        "severity": "critical",
        "expected_revision": revision,
    }

    def alert(
        name,
        expr,
        summary,
        remediation,
        current="{{ if $labels.revision }}{{ $labels.revision }}{{ else }}unknown{{ end }}",
    ):
        return {
            "alert": name,
            "expr": expr,
            "for": "5m",
            "labels": labels,
            "annotations": {
                "summary": summary,
                "current_revision": current,
                "expected_revision": revision,
                "remediation": remediation,
                "runbook_url": RUNBOOK,
            },
        }

    unknown = 'label_replace(vector(1), "revision", "unknown", "", "")'
    rules = [
        {
            "record": "dspace_release_approved_info",
            "expr": "vector(1)",
            "labels": {
                "application": "dspace",
                "environment": "staging",
                "cluster": "sugarkube-int",
                "revision": revision,
                "image_tag": tag,
                "image_digest": digest,
            },
        },
        {
            "record": "dspace_deployment_image_pin_matches",
            "expr": f'min(kube_pod_container_info{{namespace="dspace",container="dspace",image="ghcr.io/democratizedspace/dspace:{tag}"}}) and on(pod) min(kube_pod_container_status_image_id{{namespace="dspace",container="dspace",image_id=~".*@{digest}"}})',
            "labels": {
                "application": "dspace",
                "environment": "staging",
                "cluster": "sugarkube-int",
            },
        },
        alert(
            "DspaceBuildRevisionMismatch",
            f'(max by (pod, revision) (dspace_build_info{{environment="staging",revision!="{revision}"}})) or ({unknown} unless on() dspace_build_info{{environment="staging"}})',
            "DSPACE runtime revision differs from the approved release",
            "Verify build identity and pod image IDs, then reconcile to finalized evidence.",
        ),
        alert(
            "DspaceMixedBuildRevisions",
            'count(count by (revision) (dspace_build_info{environment="staging"})) > 1',
            "DSPACE replicas expose mixed build revisions",
            "Allow a settling rollout briefly; otherwise stop and reconcile every replica.",
        ),
        alert(
            "DspaceDeploymentImagePinMismatch",
            f'(max by (deployment, image) (kube_deployment_container_info{{namespace="dspace",deployment="dspace",container="dspace",image!="ghcr.io/democratizedspace/dspace:{tag}@{digest}"}})) or ({unknown} unless on() kube_deployment_container_info{{namespace="dspace",deployment="dspace",container="dspace"}})',
            "DSPACE Deployment image is not the approved immutable pin",
            "Reconcile the Deployment to the finalized tag and digest; never use a semantic tag.",
            "unknown",
        ),
        alert(
            "DspaceChatSyntheticFailed",
            f'(dspace_chat_synthetic_success{{application="dspace",environment="staging"}} == 0) or (time() - dspace_chat_synthetic_last_run_timestamp_seconds{{application="dspace",environment="staging"}} > 900) or ({unknown} unless on() dspace_chat_synthetic_last_run_timestamp_seconds{{application="dspace",environment="staging"}})',
            "DSPACE non-mutating /chat synthetic failed, is stale, or is missing",
            "Inspect freshness first, then the pinned smoke-runner result and provider configuration.",
        ),
        alert(
            "DspaceMetricsTargetDown",
            f'(max by (job) (up{{namespace="dspace",service=~"dspace.*"}}) == 0) or ({unknown} unless on() up{{namespace="dspace",service=~"dspace.*"}})',
            "DSPACE metrics target is down or missing",
            "Separate scrape/authentication failure from application health before changing DSPACE.",
            "unknown",
        ),
    ]
    return {
        "additionalPrometheusRulesMap": {
            "dspace-release-integrity": {
                "groups": [
                    {
                        "name": "sugarkube.dspace-release-integrity",
                        "interval": "30s",
                        "rules": rules,
                    }
                ]
            }
        }
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("evidence", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--rules-output", type=Path)
    a = p.parse_args()
    data = generate(json.loads(a.evidence.read_text()))
    a.output.write_text(json.dumps(data, indent=2) + "\n")
    if a.rules_output:
        a.rules_output.write_text(
            json.dumps(
                {
                    "groups": data["additionalPrometheusRulesMap"]["dspace-release-integrity"][
                        "groups"
                    ]
                },
                indent=2,
            )
            + "\n"
        )


if __name__ == "__main__":
    main()
