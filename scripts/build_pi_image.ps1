<#
  Build a Raspberry Pi OS image with cloud-init files preloaded (Windows PowerShell).
  Requirements:
    - Docker Desktop (daemon running)
    - Git (for cloning pi-gen)
    - One of: WSL (preferred) or Git Bash to run pi-gen's bash build script
    - For compression: xz.exe or 7z.exe; otherwise we'll use WSL/Docker fallback

  Environment variables respected (with defaults):
    - PI_GEN_BRANCH (default: bookworm)
    - IMG_NAME (default: sugarkube)
    - OUTPUT_DIR (default: repository root)
    - ARM64 (default: 1)
#>

[CmdletBinding()]
param(
  [string]$PiGenBranch = $(if ($env:PI_GEN_BRANCH) { $env:PI_GEN_BRANCH } else { 'bookworm' }),
  [string]$ImageName   = $(if ($env:IMG_NAME) { $env:IMG_NAME } else { 'sugarkube' }),
  [string]$OutputDir   = $(if ($env:OUTPUT_DIR) { $env:OUTPUT_DIR } else { (Resolve-Path "$PSScriptRoot\..").Path }),
  [int]$Arm64          = $(if ($env:ARM64) { [int]$env:ARM64 } else { 1 }),
  [string]$DebianMirror = $(if ($env:DEBIAN_MIRROR) { $env:DEBIAN_MIRROR } else { 'https://deb.debian.org/debian' }),
  [string]$RpiMirror    = $(if ($env:RPI_MIRROR) { $env:RPI_MIRROR } else { 'https://archive.raspberrypi.com/debian' }),
  [int]$TimeoutSec     = $(if ($env:BUILD_TIMEOUT) { [int]$env:BUILD_TIMEOUT } else { 14400 })
)

$BuildTimeout = $(if ($env:BUILD_TIMEOUT) { $env:BUILD_TIMEOUT } else { '8h' })

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Convert-ToWslLinuxPath {
  param([Parameter(Mandatory=$true)][string]$WindowsPath)
  # Normalize to absolute path
  $p = (Resolve-Path $WindowsPath).Path
  # Translate drive letter and backslashes for WSL
  if ($p -match '^[A-Za-z]:') {
    $drive = ($p.Substring(0,1)).ToLower()
    $rest = $p.Substring(2) -replace '\\','/'
    return "/mnt/$drive/$rest"
  }
  return ($p -replace '\\','/')
}

function Test-CommandAvailable {
  param([Parameter(Mandatory=$true)][string]$Name)
  if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
    Write-Error "$Name is required"
    exit 1
  }
}

function Invoke-Docker-Info {
  try {
    & docker info | Out-Null
  } catch {
    Write-Error "Docker daemon is not running or not accessible"
    exit 1
  }
}

function New-TemporaryDirectory {
  $base = [System.IO.Path]::GetTempPath()
  $name = "sugarkube-pigen-" + [System.Guid]::NewGuid().ToString('N')
  $path = Join-Path $base $name
  New-Item -ItemType Directory -Path $path | Out-Null
  return $path
}

function Convert-ToMsysPath {
  param([Parameter(Mandatory=$true)][string]$WindowsPath)
  $p = (Resolve-Path $WindowsPath).Path
  if ($p -match '^[A-Za-z]:') {
    $drive = ($p.Substring(0,1)).ToLower()
    $rest = ($p.Substring(2) -replace '\\','/').TrimStart('/')
    return "/$drive/$rest"
  }
  return ($p -replace '\\','/')
}

function Get-WSLPath {
  $candidates = @()
  if ($env:SystemRoot) { $candidates += (Join-Path $env:SystemRoot 'System32\wsl.exe') }
  if ($env:WINDIR) { $candidates += (Join-Path $env:WINDIR 'System32\wsl.exe') }
  $cmd = Get-Command wsl.exe -ErrorAction SilentlyContinue
  if ($cmd) { $candidates += $cmd.Source }
  foreach ($p in $candidates | Get-Unique) {
    if (Test-Path $p) { return $p }
  }
  return $null
}

function Get-GitBashPath {
  # Prefer Git for Windows bash over legacy WSL bash shim
  $candidates = @(
    'C:\\Program Files\\Git\\bin\\bash.exe',
    'C:\\Program Files\\Git\\usr\\bin\\bash.exe',
    'C:\\Program Files (x86)\\Git\\bin\\bash.exe',
    'C:\\Program Files (x86)\\Git\\usr\\bin\\bash.exe'
  )
  foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
  $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
  if ($cmd -and (Test-Path $cmd.Source) -and ($cmd.Source -notmatch 'System32\\bash.exe')) { return $cmd.Source }
  return $null
}

function Get-WslDistroWithBash {
  param([Parameter(Mandatory=$true)][string]$WslPath)
  $distros = (& $WslPath -l -q) -split "`r?`n" | Where-Object { $_ -and ($_ -notmatch '^docker-desktop') }
  $preferred = @('Ubuntu', 'Ubuntu-24.04', 'Ubuntu-22.04', 'Ubuntu-20.04', 'Debian')
  $ordered = @()
  foreach ($p in $preferred) { if ($distros -contains $p) { $ordered += $p } }
  foreach ($d in $distros) { if ($ordered -notcontains $d) { $ordered += $d } }
  foreach ($distro in $ordered) {
    & $WslPath -d $distro -- sh -lc "command -v bash >/dev/null 2>&1"
    if ($LASTEXITCODE -eq 0) { return $distro }
  }
  return $null
}

function Invoke-BuildPiGen {
  param(
    [Parameter(Mandatory=$true)][string]$PiGenPath,
    [Parameter(Mandatory=$true)][string]$ImageName,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [Parameter(Mandatory=$true)][string]$PiGenBranch,
    [Parameter(Mandatory=$true)][int]$Arm64,
    [Parameter(Mandatory=$true)][string]$RepoRoot,
    [int]$TimeoutSec = 14400
  )

  # Prefer Git Bash (Windows Docker) to avoid WSL Docker integration issues; fall back to WSL if needed
  $gitBash = Get-GitBashPath
  if ($gitBash) {
    $msysPath = Convert-ToMsysPath -WindowsPath $PiGenPath
    # Verify the path is visible inside Git Bash; otherwise fall back
    $testArgs = '-lc', ("test -d '" + $msysPath + "' || exit 88")
    $testProc = Start-Process -FilePath $gitBash -ArgumentList $testArgs -NoNewWindow -PassThru
    $testProc.WaitForExit() | Out-Null
    if ($testProc.ExitCode -ne 0) { $gitBash = $null }
    else {
      $cmd = "export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'; " +
        "set -exuo pipefail; cd '" + $msysPath + "' && chmod +x ./build.sh && ./build.sh"
      $args = '-lc', $cmd
      $proc = Start-Process -FilePath $gitBash -ArgumentList $args -NoNewWindow -PassThru
      if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        $proc.Kill()
        throw "pi-gen build timed out after $TimeoutSec seconds"
      }
      if ($proc.ExitCode -ne 0) {
        throw "pi-gen build failed under Git Bash (exit $($proc.ExitCode))"
      }
      return
    }
  }

  # Fallback to WSL if Git Bash not available
  $wsl = Get-WSLPath
  if ($wsl) {
    $distro = Get-WslDistroWithBash -WslPath $wsl
    if ($distro) {
      $linuxPath = Convert-ToWslLinuxPath -WindowsPath $PiGenPath
      $cmd = "set -exuo pipefail; cd '$linuxPath' && chmod +x ./build.sh && ./build.sh"
      $args = '-d', $distro, '--', 'bash', '-lc', $cmd
      $proc = Start-Process -FilePath $wsl -ArgumentList $args -NoNewWindow -PassThru
      if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
        $proc.Kill()
        throw "pi-gen build failed under WSL ($distro): timeout after $TimeoutSec seconds"
      }
      if ($proc.ExitCode -ne 0) {
        throw "pi-gen build failed under WSL ($distro) (exit $($proc.ExitCode))"
      }
      return
    }
  }

  throw "No suitable Linux shell found. Install WSL (Ubuntu recommended) or ensure wsl.exe is in PATH."
}

function Invoke-BuildPiGenDocker {
  param(
    [Parameter(Mandatory=$true)][string]$RepoRoot,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [Parameter(Mandatory=$true)][string]$PiGenBranch,
    [Parameter(Mandatory=$true)][string]$ImageName,
    [Parameter(Mandatory=$true)][int]$Arm64,
    [int]$TimeoutSec = 14400
  )

  $hostRoot = (Resolve-Path $RepoRoot).Path
  $hostOut = (Resolve-Path $OutputDir).Path
  # Ensure binfmt handlers are installed on the Docker host for ARM emulation
  & docker run --privileged --rm tonistiigi/binfmt --install arm64,arm | Out-Null
  # Do not fail hard here; some environments return non-zero despite emulators being present
  if ($LASTEXITCODE -ne 0) { Write-Warning "binfmt installer returned exit code $LASTEXITCODE; continuing" }
  # Pick a reachable Raspbian mirror to avoid intermittent outages
  $raspbianCandidates = @(
    'https://mirror.fcix.net/raspbian/raspbian',
    'https://mirrors.ocf.berkeley.edu/raspbian/raspbian',
    'https://raspbian.raspberrypi.org/raspbian',
    'https://raspbian.mirrorservice.org/raspbian',
    'https://archive.raspbian.org/raspbian'
  )
  $raspbianMirror = $raspbianCandidates[0]
  foreach ($m in $raspbianCandidates) {
    try {
      Invoke-WebRequest -Method Head -TimeoutSec 5 -Uri $m | Out-Null
      $raspbianMirror = $m
      break
    } catch { }
  }
  $bash = @'
set -e
export DEBIAN_FRONTEND=noninteractive
APT_OPTS="--fix-missing -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0"
export http_proxy="__HOST_PROXY__" https_proxy="__HOST_PROXY__" HTTP_PROXY="__HOST_PROXY__" HTTPS_PROXY="__HOST_PROXY__"
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
git clone --depth 1 --branch '__PIGEN_BRANCH__' https://github.com/RPi-Distro/pi-gen.git /work/pi-gen
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
IMG_NAME="__IMG_NAME__"
ENABLE_SSH=1
ARM64=__ARM64__
APT_MIRROR=__RASPBIAN_MIRROR__
RASPBIAN_MIRROR=__RASPBIAN_MIRROR__
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
cat > /work/pi-gen/stage0/00-configure-apt/files/etc/apt/apt.conf.d/80-retries <<EOR
Acquire::Retries "10";
Acquire::ForceIPv4 "true";
Acquire::http::Timeout "30";
Acquire::https::Timeout "30";
Acquire::http::Pipeline-Depth "0";
Acquire::Queue-Mode "access";
EOR
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
      sed -i "s#https\?://\(raspbian\.raspberrypi\.(com\|org)\|mirror\.fcix\.net\|mirrors\.ocf\.berkeley\.edu\)/raspbian#${m}#g" "$f" || true
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
if [ ! -d /proc/sys/fs/binfmt_misc ]; then
  mkdir -p /proc/sys/fs/binfmt_misc || true
fi
if ! mountpoint -q /proc/sys/fs/binfmt_misc; then
  mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc || true
fi
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
chmod +x ./build.sh
set +e
timeout __TIMEOUT__ ./build.sh
code=$?
set -e
if [ "$code" -eq 124 ]; then
  echo "pi-gen timed out after __TIMEOUT__. Retrying once without timeout..."
  ./build.sh
elif [ "$code" -ne 0 ]; then
  if grep -Rqs "Couldn't download packages" work/*/stage0/debootstrap.log; then
    echo "Transient debootstrap fetch error detected. Retrying build once..."
    ./build.sh
  else
    exit "$code"
  fi
fi
artifact=$(find deploy -maxdepth 1 -name "*.img" | head -n1)
cp "$artifact" /out/__IMG_NAME__.img
'@
  $bash = $bash.Replace('__PIGEN_BRANCH__', $PiGenBranch)
  $bash = $bash.Replace('__IMG_NAME__', $ImageName)
  $bash = $bash.Replace('__ARM64__', $Arm64.ToString())
  $bash = $bash.Replace('__TIMEOUT__', $BuildTimeout)
  $bash = $bash.Replace('__RASPBIAN_MIRROR__', $raspbianMirror)
  $bash = $bash.Replace('__HOST_PROXY__', $HostProxy)
  $bash = $bash.Replace('__APT_PROXY__', $AptProxy)
  $bashLF = ($bash -replace "`r`n","`n").Trim()

  $tempScript = Join-Path $hostRoot (".pigen-build-" + [System.Guid]::NewGuid().ToString('N') + ".sh")
  try {
    if (Test-Path $tempScript) { Remove-Item -Force -- $tempScript }
    for ($i=0; $i -lt 5; $i++) {
      try {
        $bashLF | Set-Content -NoNewline -Encoding Ascii -- $tempScript
        break
      } catch {
        Start-Sleep -Milliseconds 200
        if ($i -eq 4) { throw }
      }
    }
    & docker run --rm --privileged --network sugarkube-build -v "${hostRoot}:/host" -v "${hostOut}:/out" debian:bookworm bash -lc "bash /host/$(Split-Path -Leaf $tempScript)"
    if ($LASTEXITCODE -ne 0) { throw "pi-gen Docker run failed (exit $LASTEXITCODE)" }
  } finally {
    if (Test-Path $tempScript) { Remove-Item -Force -- $tempScript }
  }
}

function Invoke-BuildPiGenOfficial {
  param(
    [Parameter(Mandatory=$true)][string]$RepoRoot,
    [Parameter(Mandatory=$true)][string]$OutputDir,
    [Parameter(Mandatory=$true)][string]$PiGenBranch,
    [Parameter(Mandatory=$true)][string]$ImageName,
    [Parameter(Mandatory=$true)][int]$Arm64,
    [int]$TimeoutSec = 14400
  )

  $hostRoot = (Resolve-Path $RepoRoot).Path
  $hostOut = (Resolve-Path $OutputDir).Path
  & docker volume create pigen-work-cache | Out-Null
  & docker volume create pigen-apt-cache | Out-Null
  $userData = Join-Path $hostRoot 'scripts\cloud-init\user-data.yaml'
  $cfCompose = Join-Path $hostRoot 'scripts\cloud-init\docker-compose.cloudflared.yml'

  $raspbianMirror = 'http://raspbian.raspberrypi.org/raspbian'
  $archiveMirror = 'http://archive.raspberrypi.org/debian'
  $debMirror = 'http://deb.debian.org/debian'
  $securityMirror = 'http://security.debian.org/debian-security'

  # Skip if GHCR is not accessible (avoids auth errors)
  & docker manifest inspect ghcr.io/raspberrypi/pigen:latest | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "skip-official"
  }

  $dockerArgs = @(
    'run','--rm','--privileged',
    '--network','sugarkube-build',
    '-e',"IMG_NAME=$ImageName", '-e','ENABLE_SSH=1', '-e',"ARM64=$Arm64", '-e','USE_QCOW2=1',
    '-e','APT_OPTS=--fix-missing -o Acquire::Retries=10 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true -o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0',
    '-e',"APT_MIRROR=$debMirror", '-e',"DEBIAN_MIRROR=$debMirror",
    '-e',"SECURITY_MIRROR=$securityMirror",
    '-e',"RASPBIAN_MIRROR=$raspbianMirror", '-e',"APT_MIRROR_RASPBERRYPI=$archiveMirror",
    '-e','APT_COMPONENTS=main contrib non-free non-free-firmware',
    '-e','DEBOOTSTRAP_EXTRA_ARGS=--components=main,contrib,non-free,non-free-firmware',
    '-e','DEBOOTSTRAP_INCLUDE=libnftnl11',
    '-e','COMPRESSION=none',
    '-e',"http_proxy=$AptProxy", '-e',"https_proxy=$AptProxy", '-e',"HTTP_PROXY=$AptProxy", '-e',"HTTPS_PROXY=$AptProxy",
    '-e',"PI_GEN_BRANCH=$PiGenBranch",
    '-v',"${hostOut}:/pi-gen/deploy",
    '-v','pigen-work-cache:/pi-gen/work',
    '-v','pigen-apt-cache:/var/cache/apt',
    '-v',"${userData}:/pi-gen/stage2/01-sys-tweaks/user-data:ro",
    '-v',"${cfCompose}:/pi-gen/stage2/01-sys-tweaks/files/opt/sugarkube/docker-compose.cloudflared.yml:ro",
    'ghcr.io/raspberrypi/pigen:latest','bash','-lc','cd /pi-gen && ./build.sh'
  )
  & docker @dockerArgs
  if ($LASTEXITCODE -ne 0) { throw "pi-gen official image run failed (exit $LASTEXITCODE)" }
}

function Compress-XZ {
  param(
    [Parameter(Mandatory=$true)][string]$ImagePath
  )

  # Prefer native xz, then 7-Zip; fall back to WSL or a temporary Docker container
  if (Get-Command xz -ErrorAction SilentlyContinue) {
    & xz -T0 -- "$ImagePath"
    return "$ImagePath.xz"
  }

  if (Get-Command 7z -ErrorAction SilentlyContinue) {
    $xzPath = "$ImagePath.xz"
    & 7z a -txz -- "$xzPath" "$ImagePath" | Out-Null
    Remove-Item -Force -- "$ImagePath"
    return $xzPath
  }

  $wsl = Get-WSLPath
  if ($wsl) {
    $distro = Get-WslDistroWithBash -WslPath $wsl
    if ($distro) {
      $linuxImgPath = Convert-ToWslLinuxPath -WindowsPath $ImagePath
      & $wsl -d $distro -- bash -lc "xz -T0 -- '$linuxImgPath'"
      return "$ImagePath.xz"
    }
  }

  # Docker-based fallback: install xz-utils in a disposable container
  $imgDir = Split-Path -Parent "$ImagePath"
  $imgFile = Split-Path -Leaf "$ImagePath"
  & docker run --rm -v "${imgDir}:/work" -w /work debian:bookworm bash -lc "apt-get update >/dev/null 2>&1 && apt-get install -y xz-utils >/dev/null 2>&1 && xz -T0 -- '$imgFile'"
  return "$ImagePath.xz"
}

function Write-SHA256File {
  param(
    [Parameter(Mandatory=$true)][string]$FilePath
  )
  $hash = (Get-FileHash -Algorithm SHA256 $FilePath).Hash.ToLower()
  $leaf = Split-Path -Leaf $FilePath
  $out = "$FilePath.sha256"
  "${hash}  ${leaf}" | Set-Content -NoNewline $out
  return $out
}

function Ensure-DockerNetwork {
  param([Parameter(Mandatory=$true)][string]$Name)
  & docker network inspect $Name | Out-Null
  if ($LASTEXITCODE -ne 0) {
    & docker network create $Name | Out-Null
  }
}

function Ensure-AptCacheProxy {
  $net = 'sugarkube-build'
  Ensure-DockerNetwork -Name $net
  # Create persistent cache volume
  & docker volume create sugarkube-apt-cache | Out-Null
  # Start or create apt-cacher-ng container
  & docker container inspect sugarkube-apt-cache | Out-Null
  if ($LASTEXITCODE -eq 0) {
    & docker start sugarkube-apt-cache | Out-Null
  } else {
    & docker run -d --name sugarkube-apt-cache --network $net -p 3142:3142 `
      -v sugarkube-apt-cache:/var/cache/apt-cacher-ng `
      --restart unless-stopped sameersbn/apt-cacher-ng:latest | Out-Null
  }
  # Wait until proxy responds
  for ($i=0; $i -lt 20; $i++) {
    try {
      Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri 'http://localhost:3142/acng-report.html' | Out-Null
      break
    } catch { Start-Sleep -Seconds 1 }
  }
}

# Preconditions
Test-CommandAvailable docker
Test-CommandAvailable git
Invoke-Docker-Info

# Start apt-cacher-ng proxy and network for reliable apt
Ensure-AptCacheProxy
$AptProxy = 'http://sugarkube-apt-cache:3142'
$HostProxy = 'http://host.docker.internal:3142'

# Install qemu binfmt handlers so pi-gen can emulate ARM binaries without hanging
& docker run --privileged --rm tonistiigi/binfmt --install arm64,arm | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to install binfmt handlers on host" }

# Verify required mirrors and GitHub are reachable before proceeding
$urls = @($DebianMirror, $RpiMirror, 'http://raspbian.raspberrypi.org/raspbian', 'https://github.com')
foreach ($u in $urls) {
  try {
    Invoke-WebRequest -Method Head -Uri $u -TimeoutSec 10 | Out-Null
  } catch {
    Write-Error "Cannot reach $u"
    exit 1
  }
}

# Ensure Docker network and apt-cacher-ng proxy are running
Ensure-DockerNetwork -Name 'sugarkube-build'
Ensure-AptCacheProxy

# Paths and working directory
$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$workDir = New-TemporaryDirectory
try {
  $piGenDir = Join-Path $workDir 'pi-gen'

  # Clone pi-gen
  & git clone --depth 1 --branch "$PiGenBranch" https://github.com/RPi-Distro/pi-gen.git -- "$piGenDir"
  # Normalize any stale raspbian mirror references in pi-gen to the canonical .org host
  try {
    $textFileGlobs = @('*.sh','*.list','*.sources','*.cfg','config','*.conf','*.env','*.mk')
    $candidateFiles = @()
    foreach ($g in $textFileGlobs) { $candidateFiles += Get-ChildItem -Path $piGenDir -Recurse -File -Filter $g -ErrorAction SilentlyContinue }
    foreach ($f in $candidateFiles) {
      $raw = Get-Content -LiteralPath $f.FullName -Raw -ErrorAction SilentlyContinue
      if ($null -ne $raw -and $raw -match 'raspbian\.raspberrypi\.com') {
        ($raw -replace 'raspbian\.raspberrypi\.com','raspbian.raspberrypi.org') | Set-Content -NoNewline -LiteralPath $f.FullName
      }
    }
  } catch { Write-Warning "Failed to normalize raspbian mirror references: $($_.Exception.Message)" }

  # Copy cloud-init user-data
  $srcUserData = Join-Path $repoRoot 'scripts\cloud-init\user-data.yaml'
  $destDir = Join-Path $piGenDir 'stage2\01-sys-tweaks'
  New-Item -ItemType Directory -Force -Path $destDir | Out-Null
  Copy-Item -Force $srcUserData (Join-Path $destDir 'user-data')

  # Copy Cloudflare compose file
  $srcCompose = Join-Path $repoRoot 'scripts\cloud-init\docker-compose.cloudflared.yml'
  $composeDir = Join-Path $destDir 'files\opt\sugarkube'
  New-Item -ItemType Directory -Force -Path $composeDir | Out-Null
  Copy-Item -Force $srcCompose (Join-Path $composeDir 'docker-compose.cloudflared.yml')


  # Write pi-gen config
  $config = @()
  $config += ('IMG_NAME="' + $ImageName + '"')
  $config += "ENABLE_SSH=1"
  $config += "ARM64=$Arm64"
  $config += 'APT_MIRROR=http://raspbian.raspberrypi.org/raspbian'
  $config += 'RASPBIAN_MIRROR=http://raspbian.raspberrypi.org/raspbian'
  $config += 'APT_MIRROR_RASPBERRYPI=http://archive.raspberrypi.org/debian'
  $config += 'DEBIAN_MIRROR=http://deb.debian.org/debian'
  $config += 'SECURITY_MIRROR=http://security.debian.org/debian-security'
  $config += 'APT_COMPONENTS="main contrib non-free non-free-firmware"'
  $aptOpts = '--fix-missing -o Acquire::Retries=10 -o Acquire::http::Timeout=30 ' +
    '-o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true ' +
    '-o Acquire::ForceIPv4=true -o Acquire::Queue-Mode=access -o Acquire::http::Pipeline-Depth=0'
  $config += ('APT_OPTS="' + $aptOpts + '"')
  $config += 'DEBOOTSTRAP_EXTRA_ARGS="--components=main,contrib,non-free,non-free-firmware"'
  $config += 'DEBOOTSTRAP_INCLUDE="libnftnl11"'
  $config -join "`n" | Set-Content -NoNewline (Join-Path $piGenDir 'config')

  # Run the build (prefer local shell; fallback to containerized pi-gen)
  try {
    Invoke-BuildPiGen -PiGenPath $piGenDir -ImageName $ImageName -OutputDir $OutputDir -PiGenBranch $PiGenBranch -Arm64 $Arm64 -RepoRoot $repoRoot -TimeoutSec $TimeoutSec
  } catch {
    Write-Warning "Local shell build failed: $($_.Exception.Message). Trying official pigen image."
    try {
      Invoke-BuildPiGenOfficial -RepoRoot $repoRoot -OutputDir $OutputDir -PiGenBranch $PiGenBranch -ImageName $ImageName -Arm64 $Arm64 -TimeoutSec $TimeoutSec
    } catch {
      Write-Warning "Official pigen image failed: $($_.Exception.Message). Falling back to Debian container method."
      Invoke-BuildPiGenDocker -RepoRoot $repoRoot -OutputDir $OutputDir -PiGenBranch $PiGenBranch -ImageName $ImageName -Arm64 $Arm64 -TimeoutSec $TimeoutSec
    }
  }

  # Collect artifact
  $deployDir = Join-Path $piGenDir 'deploy'
  if (-not (Test-Path $deployDir)) {
    # Try OUTPUT_DIR if using containerized builds
    $maybeImg = Join-Path $OutputDir ("$ImageName.img")
    if (Test-Path $maybeImg) {
      $builtImg = Get-Item $maybeImg
    } else {
      $builtImg = Get-ChildItem -Path $OutputDir -Filter *.img -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    }
  } else {
    $builtImg = Get-ChildItem -Path $deployDir -Filter *.img -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  }
  if (-not $builtImg) { throw "No .img produced in $deployDir or $OutputDir" }

  New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
  $finalImg = Join-Path $OutputDir ("$ImageName.img")
  if ($builtImg.DirectoryName -ne (Resolve-Path $OutputDir).Path) {
    Move-Item -Force $builtImg.FullName $finalImg
  } else {
    if ($builtImg.Name -ne (Split-Path -Leaf $finalImg)) {
      Move-Item -Force $builtImg.FullName $finalImg
    }
  }

  # Compress and checksum
  $xzPath = Compress-XZ -ImagePath $finalImg
  $shaPath = Write-SHA256File -FilePath $xzPath

  # Output summary
  $xzItem = Get-Item $xzPath
  $shaItem = Get-Item $shaPath
  Write-Host ("`n{0,12}  {1}" -f ($xzItem.Length.ToString('#,0')), $xzItem.FullName)
  Write-Host ("{0,12}  {1}" -f ($shaItem.Length.ToString('#,0')), $shaItem.FullName)
  Write-Host ("`nImage written to $xzPath")
}
finally {
  if (Test-Path $workDir) {
    try { Remove-Item -Recurse -Force -- $workDir } catch { }
  }
}
