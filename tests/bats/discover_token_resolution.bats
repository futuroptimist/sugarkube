#!/usr/bin/env bats

load helpers/path_stub

bats_require_minimum_version 1.5.0

setup() {
  setup_path_stub_dir
  REPO_ROOT="${BATS_CWD:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
}

@test "staging prefers SUGARKUBE_TOKEN_STAGING over generic token" {
  run --separate-stderr env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_ENV=staging \
    SUGARKUBE_SERVERS=1 \
    SUGARKUBE_SKIP_SYSTEMCTL=1 \
    SUGARKUBE_TOKEN_STAGING="staging-env-token" \
    SUGARKUBE_TOKEN="generic-token" \
    bash "${REPO_ROOT}/scripts/k3s-discover.sh" --print-resolved-token

  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "staging-env-token" ]
  [[ "${stderr}" =~ token-source=env:SUGARKUBE_TOKEN_STAGING ]]
}

@test "staging falls back to generic token when env-specific token unset" {
  run --separate-stderr env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_ENV=staging \
    SUGARKUBE_SERVERS=1 \
    SUGARKUBE_SKIP_SYSTEMCTL=1 \
    SUGARKUBE_TOKEN="generic-token" \
    bash "${REPO_ROOT}/scripts/k3s-discover.sh" --print-resolved-token

  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "generic-token" ]
  [[ "${stderr}" =~ token-source=env:SUGARKUBE_TOKEN ]]
}

@test "deprecated int alias falls back to SUGARKUBE_TOKEN_INT when staging token empty" {
  run --separate-stderr env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_ENV=int \
    SUGARKUBE_SERVERS=1 \
    SUGARKUBE_SKIP_SYSTEMCTL=1 \
    SUGARKUBE_TOKEN_STAGING="" \
    SUGARKUBE_TOKEN_INT="legacy-int-token" \
    SUGARKUBE_TOKEN="generic-token" \
    bash "${REPO_ROOT}/scripts/k3s-discover.sh" --print-resolved-token

  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "legacy-int-token" ]
  [[ "${stderr}" == *"discover_env_alias"* ]]
  [[ "${stderr}" == *"token-source=env:SUGARKUBE_TOKEN_INT (deprecated)"* ]]
}

@test "prod prefers SUGARKUBE_TOKEN_PROD and falls back to generic token" {
  run --separate-stderr env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_ENV=prod \
    SUGARKUBE_SERVERS=1 \
    SUGARKUBE_SKIP_SYSTEMCTL=1 \
    SUGARKUBE_TOKEN_PROD="prod-specific-token" \
    SUGARKUBE_TOKEN="generic-token" \
    bash "${REPO_ROOT}/scripts/k3s-discover.sh" --print-resolved-token

  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "prod-specific-token" ]
  [[ "${stderr}" =~ token-source=env:SUGARKUBE_TOKEN_PROD ]]

  run --separate-stderr env \
    ALLOW_NON_ROOT=1 \
    SUGARKUBE_ENV=prod \
    SUGARKUBE_SERVERS=1 \
    SUGARKUBE_SKIP_SYSTEMCTL=1 \
    SUGARKUBE_TOKEN="generic-token" \
    bash "${REPO_ROOT}/scripts/k3s-discover.sh" --print-resolved-token

  [ "$status" -eq 0 ]
  [ "${lines[0]}" = "generic-token" ]
  [[ "${stderr}" =~ token-source=env:SUGARKUBE_TOKEN ]]
}
