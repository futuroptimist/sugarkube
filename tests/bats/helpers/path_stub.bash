#!/usr/bin/env bash

setup_path_stub_dir() {
  if [ -z "${_BATS_PATH_STUB_DIR:-}" ]; then
    _BATS_PATH_STUB_DIR="${BATS_TEST_TMPDIR}/path-stubs"
    mkdir -p "${_BATS_PATH_STUB_DIR}"
    PATH="${_BATS_PATH_STUB_DIR}:${PATH}"
  fi
}

stub_command() {
  local name="$1"
  shift || true
  setup_path_stub_dir
  local target="${_BATS_PATH_STUB_DIR}/${name}"
  cat >"${target}"
  chmod +x "${target}"
}

# shim_missing_command ensures a command is available in PATH when running tests
# on minimal environments. When the command already exists, it leaves the system
# binary intact unless --force is provided. When missing (or forced), it creates
# a stub via stub_command using the provided stdin body.
shim_missing_command() {
  local force=0
  if [ "$1" = "--force" ]; then
    force=1
    shift || true
  fi

  local name="$1"
  shift || true

  if [ -z "${name}" ]; then
    echo "shim_missing_command: command name required" >&2
    return 1
  fi

  if [ "${force}" -ne 1 ] && command -v "${name}" >/dev/null 2>&1; then
    return 0
  fi

  stub_command "${name}" "$@"
}
