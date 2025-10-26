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

stub_hostname() {
  local short="$1"
  local fqdn="$2"
  stub_command hostname <<EOS
#!/usr/bin/env bash
case "$1" in
  -f)
    echo "$fqdn"
    ;;
  -s)
    echo "$short"
    ;;
  "")
    echo "$short"
    ;;
  *)
    echo "$short"
    ;;
esac
EOS
}

stub_ip_with_mac() {
  local mac="$1"
  stub_command ip <<EOS
#!/usr/bin/env bash
if [ "$1" = "-o" ] && [ "$2" = "link" ]; then
  cat <<'OUT'
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP mode DEFAULT group default qlen 1000
    link/ether MAC_PLACEHOLDER brd ff:ff:ff:ff:ff:ff
OUT
  exit 0
fi
printf 'unexpected ip arguments' >&2
exit 1
EOS
  sed -i "s/MAC_PLACEHOLDER/${mac}/" "${_BATS_PATH_STUB_DIR}/ip"
}

@test "elect_leader chooses lowest hostname as winner" {
  stub_hostname "sugarkube0" "sugarkube0.local"
  stub_ip_with_mac "02:42:ac:11:00:02"

  run env \
    SUGARKUBE_SERVERS=3 \
    "${BATS_CWD}/scripts/elect_leader.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ winner=yes ]]
  [[ "$output" =~ key=sugarkube0\.local_0242ac110002 ]]
}

@test "elect_leader treats higher hostname as follower" {
  stub_hostname "sugarkube1" "sugarkube1.local"
  stub_ip_with_mac "02:42:ac:11:00:03"

  run env \
    SUGARKUBE_SERVERS=3 \
    "${BATS_CWD}/scripts/elect_leader.sh"

  [ "$status" -eq 0 ]
  [[ "$output" =~ winner=no ]]
  [[ "$output" =~ key=sugarkube1\.local_0242ac110003 ]]
}
