set -e
export DEBIAN_FRONTEND=noninteractive
APT_OPTS="--fix-missing -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
for i in 1 2 3 4 5; do
  if apt-get $APT_OPTS update; then break; fi; sleep 5;
done
for i in 1 2 3 4 5; do
  if apt-get $APT_OPTS install -y \
  quilt parted qemu-user-static debootstrap zerofree zip dosfstools \
  libcap2-bin libarchive-tools rsync xxd file kmod bc gpg pigz arch-test \
  git xz-utils ca-certificates curl bash coreutils binfmt-support; then break; fi; sleep 5;
done
#!/bin/bash
# rely on host-registered qemu binfmt (installed before container run)
mkdir -p /work
git clone --depth 1 --branch 'bookworm' https://github.com/RPi-Distro/pi-gen.git /work/pi-gen
install -D -m 0644 /host/scripts/cloud-init/user-data.yaml /work/pi-gen/stage2/01-sys-tweaks/user-data
install -D -m 0644 /host/scripts/cloud-init/docker-compose.cloudflared.yml \
  /work/pi-gen/stage2/01-sys-tweaks/files/opt/sugarkube/docker-compose.cloudflared.yml
cd /work/pi-gen
# Inject a debootstrap fallback wrapper to try multiple mirrors if fetch fails
mkdir -p /work/pi-gen/tools
cat > /work/pi-gen/tools/debootstrap-with-fallback << 'EOF'
#!/usr/bin/env bash
set -euo pipefail
log() { echo "[debootstrap-fallback] $*"; }
# Capture args; last arg is mirror
args=("$@")
mirror="${args[${#args[@]}-1]}"
# Fallback mirrors to try if initial mirror fails
fallbacks=(
  "$mirror"
  "http://raspbian.raspberrypi.com/raspbian"
  "http://mirror.fcix.net/raspbian/raspbian"
  "http://mirrors.ocf.berkeley.edu/raspbian/raspbian"
  "http://archive.raspbian.org/raspbian"
)
for m in "${fallbacks[@]}"; do
  log "Attempting debootstrap with mirror: $m"
  args[${#args[@]}-1]="$m"
  if debootstrap "${args[@]}"; then
    log "debootstrap succeeded with mirror: $m"
    exit 0
  fi
  if grep -Rqs "Couldn't download packages" stage0/debootstrap.log 2>/dev/null || true; then
    log "Transient failure with $m, trying next mirror..."
    continue
  else
    log "Non-transient failure; aborting"
    exit 1
  fi
done
log "All mirrors failed"
exit 1
EOF
chmod +x /work/pi-gen/tools/debootstrap-with-fallback
# Patch stage0 to use the wrapper (first word 'debootstrap' at call site)
sed -i 's/^\([[:space:]]*\)debootstrap /\1\/work\/pi-gen\/tools\/debootstrap-with-fallback /' /work/pi-gen/stage0/prerun.sh
cat > config <<CFG
IMG_NAME="sugarkube"
ENABLE_SSH=1
ARM64=1
APT_MIRROR=https://mirror.fcix.net/raspbian/raspbian
RASPBIAN_MIRROR=https://mirror.fcix.net/raspbian/raspbian
APT_MIRROR_RASPBERRYPI=http://archive.raspberrypi.org/debian
DEBIAN_MIRROR=http://deb.debian.org/debian
SECURITY_MIRROR=http://security.debian.org/debian-security
APT_COMPONENTS="main contrib non-free non-free-firmware"
COMPRESSION=none
DEBOOTSTRAP_EXTRA_ARGS="--components=main,contrib,non-free,non-free-firmware"
DEBOOTSTRAP_INCLUDE="libnftnl11"
APT_OPTS="--fix-missing -o Acquire::Retries=10 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
CFG
# Force Raspbian mirror to a reliable mirror (FCIX) for all later stages
mkdir -p /work/pi-gen/stage0/00-configure-apt/files/etc/apt/sources.list.d
cat > /work/pi-gen/stage0/00-configure-apt/files/etc/apt/sources.list.d/raspi.list <<EOS
deb https://mirror.fcix.net/raspbian/raspbian bookworm main contrib non-free non-free-firmware rpi
deb http://archive.raspberrypi.com/debian bookworm main
EOS
# Increase apt retries permanently in the image
mkdir -p /work/pi-gen/stage0/00-configure-apt/files/etc/apt/apt.conf.d
cat > /work/pi-gen/stage0/00-configure-apt/files/etc/apt/apt.conf.d/80-retries <<EOR
Acquire::Retries "10";
Acquire::ForceIPv4 "true";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
Acquire::http::Pipeline-Depth "0";
Acquire::Queue-Mode "access";
EOR
# Bypass apt proxy for Raspberry Pi archive to avoid 503s from apt-cacher
mkdir -p /work/pi-gen/stage0/00-configure-apt/files/etc/apt/apt.conf.d
cat > /work/pi-gen/stage0/00-configure-apt/files/etc/apt/apt.conf.d/90-proxy-exceptions <<EOP
Acquire::http::Proxy::archive.raspberrypi.com "DIRECT";
Acquire::https::Proxy::archive.raspberrypi.com "DIRECT";
EOP
# Ensure mirror rewrite happens before default 00-run.sh executes
cat > /work/pi-gen/stage0/00-configure-apt/00-run-00-pre.sh <<'EOSH'
#!/bin/bash
set -euo pipefail
shopt -s nullglob
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i 's#http://raspbian.raspberrypi.com/raspbian#https://mirror.fcix.net/raspbian/raspbian#g' "$f" || true
  sed -i -E 's#https?://raspbian\\.raspberrypi\\.(com|org)/raspbian#https://mirror.fcix.net/raspbian/raspbian#g' "$f" || true
done
EOSH
chmod +x /work/pi-gen/stage0/00-configure-apt/00-run-00-pre.sh
# Ensure any lists written by pi-gen use FCIX mirror and run a safe dist-upgrade
cat > /work/pi-gen/stage0/00-configure-apt/01-run.sh <<'EOSH'
#!/bin/bash
set -euo pipefail
shopt -s nullglob
# Try HTTPS mirrors in order: FCIX -> OCF -> raspbian.org
try_mirrors=(
  "https://mirror.fcix.net/raspbian/raspbian"
  "https://mirrors.ocf.berkeley.edu/raspbian/raspbian"
  "https://raspbian.raspberrypi.org/raspbian"
)
APT_OPTS_DEFAULT="-o Acquire::Retries=10 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
for m in "${try_mirrors[@]}"; do
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    if [ -f "$f" ]; then
      sed -i "s#https\?://[^/\r\n]*/raspbian#${m}#g" "$f" || true
      sed -i -E "s#https?://raspbian\.raspberrypi\.(com|org)/raspbian#${m}#g" "$f" || true
    fi
  done
  if apt-get $APT_OPTS_DEFAULT update; then
    if apt-get $APT_OPTS_DEFAULT -o Dpkg::Options::="--force-confnew" dist-upgrade -y; then
      break
    else
      apt-get $APT_OPTS_DEFAULT -o Dpkg::Options::="--force-confnew" dist-upgrade -y --fix-missing || true
    fi
  fi
done
EOSH
chmod +x /work/pi-gen/stage0/00-configure-apt/01-run.sh

# Mirror rewrite safeguard at stage2 as well
mkdir -p /work/pi-gen/stage2/00-configure-apt
cat > /work/pi-gen/stage2/00-configure-apt/01-run.sh <<'EOSH'
#!/bin/bash
set -euo pipefail
shopt -s nullglob
try_mirrors=(
  "https://mirror.fcix.net/raspbian/raspbian"
  "https://mirrors.ocf.berkeley.edu/raspbian/raspbian"
  "https://raspbian.raspberrypi.org/raspbian"
)
APT_OPTS_DEFAULT="-o Acquire::Retries=10 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
for m in "${try_mirrors[@]}"; do
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
    if [ -f "$f" ]; then
      sed -i "s#https\?://[^/\r\n]*/raspbian#${m}#g" "$f" || true
      sed -i -E "s#https?://raspbian\.raspberrypi\.(com|org)/raspbian#${m}#g" "$f" || true
    fi
  done
  if apt-get $APT_OPTS_DEFAULT update; then
    break
  fi
done
EOSH
chmod +x /work/pi-gen/stage2/00-configure-apt/01-run.sh
cat > /work/pi-gen/stage2/00-configure-apt/00-run-00-pre.sh <<'EOSH'
#!/bin/bash
set -euo pipefail
shopt -s nullglob
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; do
  [ -f "$f" ] || continue
  sed -i 's#http://raspbian.raspberrypi.com/raspbian#https://mirror.fcix.net/raspbian/raspbian#g' "$f" || true
  sed -i -E 's#https?://raspbian\\.raspberrypi\\.(com|org)/raspbian#https://mirror.fcix.net/raspbian/raspbian#g' "$f" || true
done
EOSH
chmod +x /work/pi-gen/stage2/00-configure-apt/00-run-00-pre.sh
if [ ! -d /proc/sys/fs/binfmt_misc ]; then
  mkdir -p /proc/sys/fs/binfmt_misc || true
fi
if ! mountpoint -q /proc/sys/fs/binfmt_misc; then
  mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc || true
fi
chmod +x ./build.sh
set +e
timeout 8h ./build.sh
code=$?
set -e
if [ "$code" -eq 124 ]; then
  echo "pi-gen timed out after 8h. Retrying once without timeout..."
  ./build.sh
elif [ "$code" -ne 0 ]; then
  if grep -Rqs "Couldn't download packages" work/*/stage0/debootstrap.log; then
    echo "Transient debootstrap fetch error detected. Retrying build once..."
    ./build.sh
  else
    exit "$code"
  fi
fi
artifact=$(find deploy -maxdepth 1 -name "*.img" | head -n1 || true)
if [ -n "$artifact" ]; then
  cp "$artifact" /out/sugarkube.img
else
  zipfile=$(find deploy -maxdepth 1 -name "*.zip" | head -n1 || true)
  if [ -n "$zipfile" ]; then
    imgname=$(bsdtar -tf "$zipfile" | grep -m1 '\.img$' || true)
    if [ -n "$imgname" ]; then
      bsdtar -xOf "$zipfile" "$imgname" > /out/sugarkube.img
    else
      echo "No .img found inside $zipfile" >&2; exit 1
    fi
  else
    echo "No image artifact found in deploy/" >&2; exit 1
  fi
fi
