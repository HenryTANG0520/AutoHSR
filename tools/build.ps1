[CmdletBinding()]
param([switch]$UpdaterOnly, [string]$PythonPath)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$taskVenvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if ($PythonPath) {
    if (-not $UpdaterOnly) { throw 'PythonPath is only for an isolated updater build.' }
    $taskVenvPython = [IO.Path]::GetFullPath($PythonPath)
}
$taskOutputDirectory = [IO.Path]::GetFullPath((Join-Path $projectRoot 'dist\AutoHSR'))
$taskStagingRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot ('build\package-' + [guid]::NewGuid().ToString('N'))))
$taskStagingOutput = Join-Path $taskStagingRoot 'AutoHSR'
$taskBackupDirectory = $null

# PyInstaller replaces its output recursively. Validate that output stays in this project.
if (-not $taskOutputDirectory.StartsWith($projectRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    $taskOutputDirectory -ne (Join-Path $projectRoot 'dist\AutoHSR')) {
    throw 'The resolved build output is outside the intended AutoHSR directory.'
}
if (-not $taskStagingRoot.StartsWith((Join-Path $projectRoot 'build') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The resolved package staging directory is outside the project build directory.'
}
if (-not (Test-Path -LiteralPath $taskVenvPython -PathType Leaf)) { throw 'Existing project Python is required.' }
foreach ($taskRequiredName in @('launcher.py', 'update_launcher.py', 'LICENSE', 'requirements.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $taskRequiredName) -PathType Leaf)) {
        throw "Required file was not found: $taskRequiredName. Run setup.ps1 first."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'assets') -PathType Container)) {
    throw 'The assets directory is missing.'
}

function Build-IndependentUpdater([string]$targetDirectory) {
    $taskUpdaterWork = Join-Path $taskStagingRoot 'updater-work'
    & $taskVenvPython -m PyInstaller --log-level WARN --noconfirm --onefile --console --name AutoHSRUpdater --distpath $targetDirectory --workpath $taskUpdaterWork --specpath $taskStagingRoot update_launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'Independent updater build failed. See output above.' }
    $taskUpdater = Join-Path $targetDirectory 'AutoHSRUpdater.exe'
    & $taskUpdater --protocol-check
    if ($LASTEXITCODE -ne 0) { throw 'Independent updater protocol check failed.' }
}

Push-Location -LiteralPath $projectRoot
try {
    & $taskVenvPython -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(''PyInstaller'') else 1)'
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller is not installed in the existing project environment. Build stopped; no dependencies installed.'
    }
    if ($UpdaterOnly) {
        $taskUpdaterOnlyOutput = Join-Path $taskStagingRoot 'updater'
        New-Item -ItemType Directory -Path $taskUpdaterOnlyOutput -Force | Out-Null
        Build-IndependentUpdater $taskUpdaterOnlyOutput
        Write-Host "Independent updater verified: $(Join-Path $taskUpdaterOnlyOutput 'AutoHSRUpdater.exe')"
        return
    }
    foreach ($taskSavedName in @('config.json', 'runs')) {
        $taskSavedPath = Join-Path $taskOutputDirectory $taskSavedName
        if (Test-Path -LiteralPath $taskSavedPath) {
            if (-not $taskBackupDirectory) {
                $taskBackupDirectory = Join-Path $projectRoot ('build\userdata-' + (Get-Date -Format 'yyyyMMdd_HHmmss_ffff'))
                New-Item -ItemType Directory -Path $taskBackupDirectory -Force | Out-Null
            }
            Copy-Item -LiteralPath $taskSavedPath -Destination $taskBackupDirectory -Recurse
        }
    }
    # Private audit captures stay beside the source, outside the runtime bundle.
    $taskAssetSourceRoot = Join-Path $projectRoot 'assets'
    $taskAssetSourcePrefix = $taskAssetSourceRoot.TrimEnd('\') + '\'
    $taskRuntimeAssets = [IO.Path]::GetFullPath((Join-Path $taskStagingRoot 'runtime-assets'))
    $taskRuntimeAssetPrefix = $taskRuntimeAssets.TrimEnd('\') + '\'
    New-Item -ItemType Directory -Path $taskRuntimeAssets -Force | Out-Null
    foreach ($taskAssetFile in Get-ChildItem -LiteralPath $taskAssetSourceRoot -Recurse -File -Force) {
        $taskAssetRelativePath = $taskAssetFile.FullName.Substring($taskAssetSourcePrefix.Length)
        if ($taskAssetRelativePath.StartsWith('currency-auto\audit\', [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $taskAssetTarget = [IO.Path]::GetFullPath((Join-Path $taskRuntimeAssets $taskAssetRelativePath))
        if (-not $taskAssetTarget.StartsWith($taskRuntimeAssetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'A staged asset path is outside the intended package staging directory.'
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $taskAssetTarget) -Force | Out-Null
        Copy-Item -LiteralPath $taskAssetFile.FullName -Destination $taskAssetTarget -Force
    }
    # Build elsewhere: Explorer or a process can keep the output directory itself open.
    & $taskVenvPython -m PyInstaller --noconfirm --onedir --windowed --name AutoHSR --distpath $taskStagingRoot `
        --icon (Join-Path $taskRuntimeAssets 'ui\autohsr.ico') `
        --collect-all rapidocr_onnxruntime --collect-all onnxruntime `
        --add-data "$taskRuntimeAssets;assets" --add-data 'LICENSE;.' launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed. See output above.' }
    $taskInternalDirectory = Join-Path $taskStagingOutput '_internal'
    Build-IndependentUpdater $taskInternalDirectory
    $taskVersion = (& $taskVenvPython -c 'from autohsr import __version__; print(__version__)').Trim()
    if ($LASTEXITCODE -ne 0 -or $taskVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Cannot resolve the portable version.' }
    [IO.File]::WriteAllText((Join-Path $taskInternalDirectory 'autohsr-version.txt'), $taskVersion, [Text.Encoding]::ASCII)
    $taskSourceRevision = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $taskSourceRevision -notmatch '^[0-9a-f]{40}$') { throw 'Cannot resolve the source revision for packaged documentation.' }
    & $taskVenvPython (Join-Path $PSScriptRoot 'stage_release_metadata.py') $taskStagingOutput $taskSourceRevision
    if ($LASTEXITCODE -ne 0) { throw 'Release documentation and license staging failed. See output above.' }
    New-Item -ItemType Directory -Path $taskOutputDirectory -Force | Out-Null
    $taskStagingPrefix = $taskStagingOutput.TrimEnd('\') + '\'
    $taskMainExecutable = Join-Path $taskStagingOutput 'AutoHSR.exe'
    # Copy dependencies first and publish the executable last. User data stays in place.
    $taskPackageFiles = @(Get-ChildItem -LiteralPath $taskStagingOutput -Recurse -File -Force |
        Where-Object { $_.FullName -ne $taskMainExecutable })
    $taskPackageFiles += Get-Item -LiteralPath $taskMainExecutable
    foreach ($taskPackageFile in $taskPackageFiles) {
        $taskRelativePath = $taskPackageFile.FullName.Substring($taskStagingPrefix.Length)
        $taskTargetPath = Join-Path $taskOutputDirectory $taskRelativePath
        New-Item -ItemType Directory -Path (Split-Path -Parent $taskTargetPath) -Force | Out-Null
        Copy-Item -LiteralPath $taskPackageFile.FullName -Destination $taskTargetPath -Force
    }
    Write-Host "Build complete: $(Join-Path $taskOutputDirectory 'AutoHSR.exe')"
} finally {
    if ($taskBackupDirectory) {
        Write-Host "Configuration and run evidence left in place. Recovery copy: $taskBackupDirectory"
    }
    Pop-Location
}
