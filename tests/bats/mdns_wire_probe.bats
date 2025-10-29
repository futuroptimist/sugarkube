#!/usr/bin/env bats

load helpers/path_stub

setup() {
  setup_path_stub_dir
}

@test "mdns_wire_probe reports established via dbus" {
  stub_command gdbus <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" != "call" ]; then
  echo "unexpected invocation" >&2
  exit 1
fi
path=""
method=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --object-path)
      path="$2"
      shift 2
      ;;
    --method)
      method="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [ "${method}" = "org.freedesktop.DBus.Introspectable.Introspect" ]; then
  case "${path}" in
    /)
      printf "('<node>\n  <node name=\"org/freedesktop/Avahi\"/>\n</node>',)\n"
      ;;
    /org/freedesktop/Avahi)
      printf "('<node>\n  <node name=\"Server\"/>\n</node>',)\n"
      ;;
    /org/freedesktop/Avahi/Server)
      printf "('<node>\n  <node name=\"EntryGroup0\"/>\n</node>',)\n"
      ;;
    /org/freedesktop/Avahi/Server/EntryGroup0)
      printf "('<node/>',)\n"
      ;;
    *)
      printf "('<node/>',)\n"
      ;;
  esac
elif [ "${method}" = "org.freedesktop.Avahi.EntryGroup.GetState" ]; then
  printf "(2,)\n"
else
  printf "()\n"
fi
STUB

  run "${BATS_CWD}/scripts/mdns_wire_probe.sh"

  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [[ "${lines[0]}" =~ status=established ]]
  [[ "${lines[0]}" =~ dbus_rc=0 ]]
  [[ "${lines[0]}" =~ dbus_summary= ]]
}

@test "mdns_wire_probe falls back to cli when dbus unavailable" {
  stub_command gdbus <<'STUB'
#!/usr/bin/env bash
exit 1
STUB

  stub_command tcpdump <<'STUB'
#!/usr/bin/env bash
exit 0
STUB

  stub_command avahi-browse <<'STUB'
#!/usr/bin/env bash
printf 'no-visible-results\n'
exit 0
STUB

  run "${BATS_CWD}/scripts/mdns_wire_probe.sh"

  [ "$status" -eq 0 ]
  [ "${#lines[@]}" -eq 1 ]
  [[ "${lines[0]}" =~ status=indeterminate ]]
  [[ "${lines[0]}" =~ reason=dbus_error ]]
  [[ "${lines[0]}" =~ browse_output= ]]
}
