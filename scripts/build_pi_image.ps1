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

$BuildTimeout = $(if ($env:BUILD_TIMEOUT) { $env:BUILD_TIMEOUT } else { '4h' })

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
  $cmd = Get-Command bash.exe -ErrorAction SilentlyContinue
  if ($cmd -and (Test-Path $cmd.Source)) { return $cmd.Source }
  $candidates = @(
    'C:\Program Files\Git\bin\bash.exe',
    'C:\Program Files\Git\usr\bin\bash.exe',
    'C:\Program Files (x86)\Git\bin\bash.exe',
    'C:\Program Files (x86)\Git\usr\bin\bash.exe'
  )
  foreach ($p in $candidates) { if (Test-Path $p) { return $p } }
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
    $cmd = "export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'; " +
      "set -exuo pipefail; cd '$msysPath' && chmod +x ./build.sh && ./build.sh"
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
  $proc = Start-Process -FilePath docker -ArgumentList @(
    'run','--privileged','--rm','tonistiigi/binfmt','--install','arm64,arm'
  ) -NoNewWindow -PassThru
  if (-not $proc.WaitForExit(600000)) { $proc.Kill() }
  if ($proc.ExitCode -ne 0) { throw "Failed to install binfmt handlers on host" }
  $bash = @'
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update
apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y \
  quilt parted qemu-user-static debootstrap zerofree zip dosfstools \
  libcap2-bin libarchive-tools rsync xxd file kmod bc gpg pigz arch-test \
  git xz-utils ca-certificates curl bash coreutils binfmt-support
#!/bin/bash
# rely on host-registered qemu binfmt (installed before container run)
mkdir -p /work
git clone --depth 1 --branch '{0}' https://github.com/RPi-Distro/pi-gen.git /work/pi-gen
install -D -m 0644 /host/scripts/cloud-init/user-data.yaml /work/pi-gen/stage2/01-sys-tweaks/user-data
install -D -m 0644 /host/scripts/cloud-init/docker-compose.cloudflared.yml \
  /work/pi-gen/stage2/01-sys-tweaks/files/opt/sugarkube/docker-compose.cloudflared.yml
cd /work/pi-gen
cat > config <<CFG
IMG_NAME="{1}"
ENABLE_SSH=1
ARM64={2}
APT_MIRROR=http://raspbian.raspberrypi.org/raspbian
RASPBIAN_MIRROR=http://raspbian.raspberrypi.org/raspbian
APT_MIRROR_RASPBERRYPI=http://archive.raspberrypi.org/debian
DEBIAN_MIRROR=http://deb.debian.org/debian
APT_OPTS="-o Acquire::Retries=5 -o Acquire::http::Timeout=30 \
-o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true"
CFG
# Ensure binfmt_misc mount exists for pi-gen checks (harmless if already mounted)
if [ ! -d /proc/sys/fs/binfmt_misc ]; then
  mkdir -p /proc/sys/fs/binfmt_misc || true
fi
if ! mountpoint -q /proc/sys/fs/binfmt_misc; then
  mount -t binfmt_misc binfmt_misc /proc/sys/fs/binfmt_misc || true
fi
chmod +x ./build.sh
timeout {3} ./build.sh
artifact=$(find deploy -maxdepth 1 -name "*.img" | head -n1)
cp "$artifact" /out/{1}.img
'@ -f $PiGenBranch, $ImageName, $Arm64, $BuildTimeout
  $bashLF = ($bash -replace "`r`n","`n").Trim()

  $tempScript = Join-Path $hostRoot '.pigen-build.sh'
  try {
    $bashLF | Set-Content -NoNewline -Encoding Ascii -- $tempScript
    $args = @(
      'run','--rm','--privileged','-v',"${hostRoot}:/host",'-v',
      "${hostOut}:/out",'debian:bookworm','bash','-lc','bash /host/.pigen-build.sh'
    )
    $proc = Start-Process -FilePath docker -ArgumentList $args -NoNewWindow -PassThru
    if (-not $proc.WaitForExit($TimeoutSec * 1000)) {
      $proc.Kill()
      throw "pi-gen Docker run timed out after $TimeoutSec seconds"
    }
    if ($proc.ExitCode -ne 0) { throw "pi-gen Docker run failed (exit $($proc.ExitCode))" }
  } finally {
    if (Test-Path $tempScript) { Remove-Item -Force -- $tempScript }
  }
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

# Preconditions
Test-CommandAvailable docker
Test-CommandAvailable git
Invoke-Docker-Info

# Install qemu binfmt handlers so pi-gen can emulate ARM binaries without hanging
& docker run --privileged --rm tonistiigi/binfmt --install arm64,arm | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Failed to install binfmt handlers on host" }

# Verify required mirrors and GitHub are reachable before proceeding
$urls = @($DebianMirror, $RpiMirror, 'https://github.com')
foreach ($u in $urls) {
  try {
    Invoke-WebRequest -Method Head -Uri $u -TimeoutSec 10 | Out-Null
  } catch {
    Write-Error "Cannot reach $u"
    exit 1
  }
}

# Paths and working directory
$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$workDir = New-TemporaryDirectory
try {
  $piGenDir = Join-Path $workDir 'pi-gen'

  # Clone pi-gen
  & git clone --depth 1 --branch "$PiGenBranch" https://github.com/RPi-Distro/pi-gen.git -- "$piGenDir"

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
  $aptOpts = '-o Acquire::Retries=5 -o Acquire::http::Timeout=30 ' +
    '-o Acquire::https::Timeout=30 -o Acquire::http::NoCache=true'
  $config += ('APT_OPTS="' + $aptOpts + '"')
  $config -join "`n" | Set-Content -NoNewline (Join-Path $piGenDir 'config')
}

  # Run the build (prefer local shell; fallback to containerized pi-gen)
  try {
    Invoke-BuildPiGen -PiGenPath $piGenDir -ImageName $ImageName -OutputDir $OutputDir -PiGenBranch $PiGenBranch -Arm64 $Arm64 -RepoRoot $repoRoot -TimeoutSec $TimeoutSec
  } catch {
    Write-Warning "Local shell build failed: $($_.Exception.Message). Falling back to Dockerized pi-gen."
    Invoke-BuildPiGenDocker -RepoRoot $repoRoot -OutputDir $OutputDir -PiGenBranch $PiGenBranch -ImageName $ImageName -Arm64 $Arm64 -TimeoutSec $TimeoutSec
  }

  # Collect artifact
  $deployDir = Join-Path $piGenDir 'deploy'
  if (-not (Test-Path $deployDir)) { throw "pi-gen did not produce a deploy directory. See build logs above." }
  $builtImg = Get-ChildItem -Path $deployDir -Filter *.img -ErrorAction Stop | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $builtImg) { throw "No .img produced in $deployDir" }

  New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
  $finalImg = Join-Path $OutputDir ("$ImageName.img")
  Move-Item -Force $builtImg.FullName $finalImg

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
