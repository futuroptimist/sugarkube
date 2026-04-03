#!/usr/bin/env bats

load helpers/path_stub

setup() {
  ORIGINAL_PATH="$PATH"
  unset _BATS_PATH_STUB_DIR
  PATH="$ORIGINAL_PATH"
  setup_path_stub_dir
}

teardown() {
  PATH="$ORIGINAL_PATH"
}

@test "tailscale remote ops status delegates to tailscale status" {
  stub_command tailscale <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >"${BATS_TEST_TMPDIR}/tailscale-args.log"
EOS

  run env PATH="$PATH" "${BATS_CWD}/scripts/tailscale_remote_ops.sh" status -- --json

  [ "$status" -eq 0 ]
  [ "$(cat "${BATS_TEST_TMPDIR}/tailscale-args.log")" = "status --json" ]
}

@test "tailscale remote ops up loads key from file and uses sudo tailscale" {
  cat <<'KEY' >"${BATS_TEST_TMPDIR}/authkey"
tskey-auth-e2e
KEY

  stub_command tailscale <<'EOS'
#!/usr/bin/env bash
exit 0
EOS

  stub_command sudo <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >"${BATS_TEST_TMPDIR}/sudo-args.log"
EOS

  run env \
    PATH="$PATH" \
    TS_AUTHKEY_FILE="${BATS_TEST_TMPDIR}/authkey" \
    "${BATS_CWD}/scripts/tailscale_remote_ops.sh" up -- --ssh

  [ "$status" -eq 0 ]
  [ "$(cat "${BATS_TEST_TMPDIR}/sudo-args.log")" = "tailscale up --auth-key tskey-auth-e2e --ssh" ]
}
