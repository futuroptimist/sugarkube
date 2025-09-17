[CmdletBinding(SupportsShouldProcess=$true)]
param(
    [string]$Image,
    [int]$DiskNumber,
    [switch]$List,
    [switch]$DryRun,
    [switch]$SkipEject,
    [switch]$Force
)

function Get-SugarkubeDefaultImage {
    $root = Join-Path -Path ([Environment]::GetFolderPath('UserProfile')) -ChildPath 'sugarkube\images'
    if (-not (Test-Path -LiteralPath $root)) {
        return $null
    }
    $files = Get-ChildItem -LiteralPath $root -File -Filter '*.img*' | Sort-Object LastWriteTime -Descending
    return $files | Select-Object -First 1
}

function Get-RemovableDisks {
    Get-Disk | Where-Object { $_.BusType -in @('USB','SD') -or $_.IsBoot -eq $false } |
        Where-Object { $_.PartitionStyle -ne 'RAW' -or $_.IsReadOnly -eq $false }
}

if ($List) {
    $disks = Get-RemovableDisks
    if (-not $disks) {
        Write-Warning 'No removable disks detected'
        exit 1
    }
    $disks | Select-Object Number, FriendlyName, @{n='SizeGB';e={[Math]::Round($_.Size/1GB,2)}} | Format-Table -AutoSize
    exit 0
}

if (-not $Image) {
    $candidate = Get-SugarkubeDefaultImage
    if (-not $candidate) {
        throw "No image path provided and no default found"
    }
    $Image = $candidate.FullName
}

if (-not (Test-Path -LiteralPath $Image)) {
    throw "Image not found: $Image"
}

if ($DryRun) {
    if (-not $DiskNumber) {
        Write-Output "Dry run: would flash $Image."
    } else {
        Write-Output "Dry run: would flash $Image to PhysicalDrive$DiskNumber."
    }
    exit 0
}

if (-not $DiskNumber) {
    throw "Specify -DiskNumber to select a target device"
}

$disk = Get-Disk -Number $DiskNumber -ErrorAction Stop
if ($disk.BusType -notin @('USB','SD') -and -not $Force) {
    throw "Disk $DiskNumber does not appear removable. Use -Force to override."
}

if (-not $Force) {
    $prompt = "About to erase PhysicalDrive$DiskNumber ($($disk.FriendlyName)). Type the disk number to continue:"
    $confirm = Read-Host $prompt
    if ($confirm -ne "$DiskNumber") {
        throw "Confirmation mismatch"
    }
}

$devicePath = "\\.\PhysicalDrive$DiskNumber"
$bufferSize = 4MB
$buffer = New-Object byte[] $bufferSize

function New-ImageStream {
    param([string]$Path)
    if ($Path.ToLower().EndsWith('.xz')) {
        $xz = Get-Command xz -ErrorAction SilentlyContinue
        if (-not $xz) {
            throw "xz.exe not found. Install XZ Utils and ensure it is on PATH."
        }
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $xz.Source
        $psi.Arguments = "-dc -- `"$Path`""
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        return @{ Stream = $proc.StandardOutput.BaseStream; Process = $proc }
    }
    $stream = [System.IO.File]::OpenRead($Path)
    return @{ Stream = $stream; Process = $null }
}

$streamInfo = New-ImageStream -Path $Image
$inputStream = $streamInfo.Stream
$writer = [System.IO.File]::Open($devicePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
$hasher = [System.Security.Cryptography.SHA256]::Create()
$bytesWritten = 0L
try {
    while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $writer.Write($buffer, 0, $read)
        $hasher.TransformBlock($buffer, 0, $read, $null, 0) | Out-Null
        $bytesWritten += $read
        $percent = if ($disk.Size -gt 0) { [Math]::Min(100, ($bytesWritten / $disk.Size) * 100) } else { 0 }
        Write-Progress -Activity "Writing image" -Status ("{0:N0} MB" -f ($bytesWritten/1MB)) -PercentComplete $percent
    }
    $hasher.TransformFinalBlock([byte[]]::new(0),0,0) | Out-Null
    $expectedHash = ($hasher.Hash | ForEach-Object { $_.ToString('x2') }) -join ''
} finally {
    $inputStream.Dispose()
    if ($streamInfo.Process) {
        $streamInfo.Process.WaitForExit()
        $streamInfo.Process.Dispose()
    }
    $writer.Flush()
    $writer.Dispose()
}

$verifyHasher = [System.Security.Cryptography.SHA256]::Create()
$reader = [System.IO.File]::Open($devicePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
try {
    $remaining = $bytesWritten
    while ($remaining -gt 0) {
        $chunk = [Math]::Min($buffer.Length, $remaining)
        $read = $reader.Read($buffer, 0, $chunk)
        if ($read -le 0) { break }
        $verifyHasher.TransformBlock($buffer, 0, $read, $null, 0) | Out-Null
        $remaining -= $read
    }
    $verifyHasher.TransformFinalBlock([byte[]]::new(0),0,0) | Out-Null
    $actualHash = ($verifyHasher.Hash | ForEach-Object { $_.ToString('x2') }) -join ''
} finally {
    $reader.Dispose()
}

if ($expectedHash -ne $actualHash) {
    throw "Verification failed. Expected $expectedHash but read $actualHash"
}

if (-not $SkipEject) {
    try {
        Get-Volume -DiskNumber $DiskNumber -ErrorAction Stop | Dismount-Volume -Force -Confirm:$false | Out-Null
    } catch {}
    try {
        Set-Disk -Number $DiskNumber -IsOffline $true -Confirm:$false | Out-Null
    } catch {}
}

[PSCustomObject]@{
    DiskNumber = $DiskNumber
    BytesWritten = $bytesWritten
    Sha256 = $expectedHash
    Image = $Image
}
