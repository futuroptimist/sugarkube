#!/usr/bin/env bash
# shellcheck shell=bash

# Guard against multiple sourcing.
if [ -n "${SUGARKUBE_FS_LIB_SOURCED:-}" ]; then
  return 0
fi
SUGARKUBE_FS_LIB_SOURCED=1

# Ensure the process umask is set to the desired value.
# Usage: fs::ensure_umask 022
fs::ensure_umask() {
  local desired
  desired="$1"
  if [ -z "${desired}" ]; then
    echo "fs::ensure_umask requires a numeric umask value" >&2
    return 1
  fi

  case "${desired}" in
    [0-7][0-7][0-7]) ;;
    [0-7][0-7][0-7][0-7]) ;;
    *)
      echo "Invalid umask value: ${desired}" >&2
      return 1
      ;;
  esac

  umask "${desired}"
}

# Apply mode/ownership metadata to a file.
# Usage: fs::apply_metadata <path> <mode> <owner> <group>
fs::apply_metadata() {
  local path mode owner group spec
  path="$1"
  mode="$2"
  owner="$3"
  group="$4"

  if [ ! -e "${path}" ]; then
    echo "fs::apply_metadata: ${path} does not exist" >&2
    return 1
  fi

  if [ -n "${mode}" ]; then
    chmod "${mode}" "${path}"
  fi

  spec=""
  if [ -n "${owner}" ]; then
    spec="${owner}"
  fi
  if [ -n "${group}" ]; then
    if [ -n "${spec}" ]; then
      spec+=":${group}"
    else
      spec=":${group}"
    fi
  fi

  if [ -n "${spec}" ]; then
    chown "${spec}" "${path}"
  fi
}

# Atomically replace the destination with the source file after applying metadata.
# Usage: fs::atomic_install <src> <dest> <mode> <owner> <group>
fs::atomic_install() {
  local src dest mode owner group
  src="$1"
  dest="$2"
  mode="$3"
  owner="$4"
  group="$5"

  if [ -z "${src}" ] || [ -z "${dest}" ]; then
    echo "fs::atomic_install requires source and destination paths" >&2
    return 1
  fi

  if [ ! -e "${src}" ]; then
    echo "fs::atomic_install: source ${src} missing" >&2
    return 1
  fi

  fs::apply_metadata "${src}" "${mode}" "${owner}" "${group}"

  mv -f "${src}" "${dest}"
}
