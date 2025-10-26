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
