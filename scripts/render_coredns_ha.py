#!/usr/bin/env python3
"""Clone the live K3s-packaged CoreDNS Deployment into a supplemental HA Deployment."""

import json
import sys

source = json.load(sys.stdin)
if source.get("kind") != "Deployment" or source.get("metadata", {}).get("name") != "coredns":
    raise SystemExit("ERROR: expected the kube-system/coredns Deployment")
for key in (
    "uid",
    "resourceVersion",
    "generation",
    "creationTimestamp",
    "managedFields",
    "ownerReferences",
):
    source["metadata"].pop(key, None)
source.pop("status", None)
metadata = source["metadata"]
metadata["name"] = "coredns-ha"
metadata.setdefault("labels", {})["app.kubernetes.io/managed-by"] = "sugarkube-staging-ingress-ha"
spec = source.setdefault("spec", {})
spec["replicas"] = 2
spec["revisionHistoryLimit"] = 2
pod_spec = spec["template"]["spec"]
affinity = pod_spec.setdefault("affinity", {})
pod_affinity = affinity.setdefault("podAntiAffinity", {})
pod_affinity["requiredDuringSchedulingIgnoredDuringExecution"] = [
    {
        "labelSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        "topologyKey": "kubernetes.io/hostname",
    }
]
print(json.dumps(source, sort_keys=True, indent=2))
