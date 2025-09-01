set -e
export DEBIAN_FRONTEND=noninteractive
APT_OPTS="--fix-missing -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
export http_proxy="http://sugarkube-apt-cache:3142" https_proxy="http://sugarkube-apt-cache:3142" HTTP_PROXY="http://sugarkube-apt-cache:3142" HTTPS_PROXY="http://sugarkube-apt-cache:3142"
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
cat > config <<CFG
IMG_NAME="sugarkube"
ENABLE_SSH=1
ARM64=1
APT_MIRROR=http://raspbian.raspberrypi.org/raspbian
RASPBIAN_MIRROR=http://raspbian.raspberrypi.org/raspbian
APT_MIRROR_RASPBERRYPI=http://archive.raspberrypi.org/debian
DEBIAN_MIRROR=http://deb.debian.org/debian
COMPRESSION=none
APT_PROXY=http://sugarkube-apt-cache:3142
APT_OPTS="--fix-missing -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
CFG
# Ensure binfmt_misc mount exists for pi-gen checks (harmless if already mounted)
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
  exit "$code"
fi
artifact=$(find deploy -maxdepth 1 -name "*.img" | head -n1)
cp "$artifact" /out/sugarkube.img
