param(
    [string]$IsaacModDir = "",
    [ValidateSet("Junction", "Copy")]
    [string]$Method = "Junction",
    [switch]$InstallBoth
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$modSrc = Join-Path $repoRoot "mod"
$modName = "IsaacRL"

if (-not (Test-Path $modSrc)) {
    throw "Mod source directory not found: $modSrc"
}

function Get-DefaultModDirs {
    $dirs = @()

    $steamMods = Join-Path ${env:ProgramFiles(x86)} "Steam\steamapps\common\The Binding of Isaac Rebirth\mods"
    $docsMods = Join-Path $env:USERPROFILE "Documents\My Games\Binding of Isaac Repentance\mods"

    if (Test-Path $steamMods) { $dirs += $steamMods }
    if (Test-Path $docsMods) { $dirs += $docsMods }

    # If both are missing, create the Documents path as fallback.
    if ($dirs.Count -eq 0) { $dirs += $docsMods }

    return $dirs
}

$targetRoots = @()
if ($IsaacModDir) {
    $targetRoots += $IsaacModDir
} elseif ($InstallBoth) {
    $targetRoots += Get-DefaultModDirs
} else {
    $targetRoots += (Get-DefaultModDirs | Select-Object -First 1)
}

foreach ($root in $targetRoots) {
    New-Item -ItemType Directory -Force -Path $root | Out-Null
    $target = Join-Path $root $modName

    if (Test-Path $target) {
        Remove-Item -Recurse -Force $target
    }

    if ($Method -eq "Junction") {
        try {
            New-Item -ItemType Junction -Path $target -Target $modSrc | Out-Null
            Write-Host "Installed (junction): $target -> $modSrc"
            continue
        } catch {
            Write-Warning "Junction failed at $target. Falling back to copy. Error: $($_.Exception.Message)"
        }
    }

    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item -Recurse -Force (Join-Path $modSrc "*") $target
    Write-Host "Installed (copy): $target"
}

