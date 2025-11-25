#!/usr/bin/env bash

TRAEFIK_GATEWAY_CRDS=(
    backendtlspolicies.gateway.networking.k8s.io
    gatewayclasses.gateway.networking.k8s.io
    gateways.gateway.networking.k8s.io
    grpcroutes.gateway.networking.k8s.io
    httproutes.gateway.networking.k8s.io
    referencegrants.gateway.networking.k8s.io
)

TRAEFIK_ACCEPTED_RELEASES=(traefik traefik-crd)

traefik_collect_gateway_crd_state() {
    local namespace="$1"

    declare -gA GATEWAY_CRD_CLASS
    declare -gA GATEWAY_CRD_MANAGED_BY
    declare -gA GATEWAY_CRD_RELEASE_NAME
    declare -gA GATEWAY_CRD_RELEASE_NAMESPACE

    GATEWAY_CRD_CLASS=()
    GATEWAY_CRD_MANAGED_BY=()
    GATEWAY_CRD_RELEASE_NAME=()
    GATEWAY_CRD_RELEASE_NAMESPACE=()

    for crd in "${TRAEFIK_GATEWAY_CRDS[@]}"; do
        if ! kubectl get "crd/${crd}" >/dev/null 2>&1; then
            GATEWAY_CRD_CLASS["${crd}"]="missing"
            GATEWAY_CRD_MANAGED_BY["${crd}"]=""
            GATEWAY_CRD_RELEASE_NAME["${crd}"]=""
            GATEWAY_CRD_RELEASE_NAMESPACE["${crd}"]=""
            continue
        fi

        local managed_by release_name release_ns
        managed_by=$(kubectl get "crd/${crd}" \
            -o jsonpath='{.metadata.labels.app\\.kubernetes\\.io/managed-by}' 2>/dev/null || echo "")
        release_name=$(kubectl get "crd/${crd}" \
            -o jsonpath='{.metadata.annotations.meta\\.helm\\.sh/release-name}' 2>/dev/null || echo "")
        release_ns=$(kubectl get "crd/${crd}" \
            -o jsonpath='{.metadata.annotations.meta\\.helm\\.sh/release-namespace}' 2>/dev/null || echo "")

        GATEWAY_CRD_MANAGED_BY["${crd}"]="${managed_by}"
        GATEWAY_CRD_RELEASE_NAME["${crd}"]="${release_name}"
        GATEWAY_CRD_RELEASE_NAMESPACE["${crd}"]="${release_ns}"

        local release_ok=0
        for accepted in "${TRAEFIK_ACCEPTED_RELEASES[@]}"; do
            if [ "${release_name}" = "${accepted}" ]; then
                release_ok=1
                break
            fi
        done

        if [ "${managed_by}" = "Helm" ] && [ "${release_ns}" = "${namespace}" ] && [ "${release_ok}" -eq 1 ]; then
            GATEWAY_CRD_CLASS["${crd}"]="ok"
        else
            GATEWAY_CRD_CLASS["${crd}"]="problem"
        fi
    done
}
