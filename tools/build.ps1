[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$taskVenvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
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
foreach ($taskRequiredName in @('.venv\Scripts\python.exe', 'launcher.py', 'LICENSE', 'requirements.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $taskRequiredName) -PathType Leaf)) {
        throw "Required file was not found: $taskRequiredName. Run setup.ps1 first."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'assets') -PathType Container)) {
    throw 'The assets directory is missing.'
}

Push-Location -LiteralPath $projectRoot
try {
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
    & $taskVenvPython -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(''PyInstaller'') else 1)'
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller is not installed in the existing project environment. Build stopped; no dependencies installed.'
    }
    # Build elsewhere: Explorer or a process can keep the output directory itself open.
    & $taskVenvPython -m PyInstaller --noconfirm --onedir --windowed --name AutoHSR --distpath $taskStagingRoot `
        --collect-all rapidocr_onnxruntime --collect-all onnxruntime `
        --add-data 'assets;assets' --add-data 'LICENSE;.' launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed. See output above.' }
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
    Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') -Destination (Join-Path $taskOutputDirectory 'LICENSE') -Force
    $taskSourceRevision = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $taskSourceRevision -notmatch '^[0-9a-f]{40}$') { throw 'Cannot resolve the source revision for packaged documentation.' }
    $taskSourceUrl = 'https://github.com/HenryTANG0520/AutoHSR/blob/' + $taskSourceRevision + '/'
    foreach ($taskDocument in @('README.md', 'DAILY_FLOW.md', 'VALIDATION.md', 'CURRENCY_WARS.md', 'CURRENCY_WARS_GUIDE.md', 'LICENSE_NOTICE.md')) {
        $taskDocumentPath = Join-Path $projectRoot $taskDocument
        if (Test-Path -LiteralPath $taskDocumentPath -PathType Leaf) {
            $taskDocumentText = (Get-Content -LiteralPath $taskDocumentPath -Raw -Encoding UTF8).Replace('](assets/', '](_internal/assets/').Replace('](runs/', '](../../runs/').Replace('](dist/AutoHSR/runs/', '](runs/').Replace('](autohsr/', '](' + $taskSourceUrl + 'autohsr/').Replace('](AGENTS.md)', '](' + $taskSourceUrl + 'AGENTS.md)')
            Set-Content -LiteralPath (Join-Path $taskOutputDirectory $taskDocument) -Value $taskDocumentText -Encoding UTF8
        }
    }
    $taskDocsDirectory = Join-Path $taskOutputDirectory 'docs'
    New-Item -ItemType Directory -Path $taskDocsDirectory -Force | Out-Null
    foreach ($taskModeDocument in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'docs') -File -Filter '*.md') {
        $taskModeDocumentText = (Get-Content -LiteralPath $taskModeDocument.FullName -Raw -Encoding UTF8).Replace('](../assets/', '](../_internal/assets/').Replace('](../runs/', '](../../../runs/').Replace('](../autohsr/', '](' + $taskSourceUrl + 'autohsr/')
        Set-Content -LiteralPath (Join-Path $taskDocsDirectory $taskModeDocument.Name) -Value $taskModeDocumentText -Encoding UTF8
    }
    Write-Host "Build complete: $(Join-Path $taskOutputDirectory 'AutoHSR.exe')"
} finally {
    if ($taskBackupDirectory) {
        Write-Host "Configuration and run evidence left in place. Recovery copy: $taskBackupDirectory"
    }
    Pop-Location
}
