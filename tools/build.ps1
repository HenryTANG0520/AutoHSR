[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$taskVenvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$taskLauncher = Join-Path $projectRoot 'launcher.py'
$taskLicense = Join-Path $projectRoot 'LICENSE'
$taskReadme = Join-Path $projectRoot 'README.md'
$taskDailyFlow = Join-Path $projectRoot 'DAILY_FLOW.md'
$taskAssets = Join-Path $projectRoot 'assets'
$taskOutputDirectory = Join-Path $projectRoot 'dist\AutoHSR'
$taskBackupDirectory = $null

foreach ($taskRequiredFile in @($taskVenvPython, $taskLauncher, $taskLicense, $taskReadme, $taskDailyFlow)) {
    if (-not (Test-Path -LiteralPath $taskRequiredFile -PathType Leaf)) {
        throw "Required file was not found: $taskRequiredFile. Run setup.ps1 first."
    }
}
if (-not (Test-Path -LiteralPath $taskAssets -PathType Container)) {
    throw 'The assets directory is missing.'
}

Push-Location -LiteralPath $projectRoot
try {
    # PyInstaller replaces COLLECT output. Preserve the user's local settings
    # and run evidence even if packaging fails midway.
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
        Write-Host 'Installing PyInstaller into the project virtual environment...'
        & $taskVenvPython -m pip install --disable-pip-version-check PyInstaller
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller installation failed.' }
    }

    & $taskVenvPython -m PyInstaller --noconfirm --onedir --windowed --name AutoHSR `
        --collect-all rapidocr_onnxruntime --collect-all onnxruntime `
        --add-data 'assets;assets' --add-data 'LICENSE;.' launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed. See the build output above.' }

    Copy-Item -LiteralPath $taskLicense -Destination (Join-Path $taskOutputDirectory 'LICENSE') -Force
    $taskNoticeText = (Get-Content -LiteralPath (Join-Path $projectRoot 'LICENSE_NOTICE.md') -Raw).Replace('](assets/', '](_internal/assets/')
    Set-Content -LiteralPath (Join-Path $taskOutputDirectory 'LICENSE_NOTICE.md') -Value $taskNoticeText -Encoding UTF8
    $taskReadmeText = (Get-Content -LiteralPath $taskReadme -Raw).Replace('](assets/', '](_internal/assets/')
    Set-Content -LiteralPath (Join-Path $taskOutputDirectory 'README.md') -Value $taskReadmeText -Encoding UTF8
    Copy-Item -LiteralPath $taskDailyFlow -Destination (Join-Path $taskOutputDirectory 'DAILY_FLOW.md') -Force
    $taskValidation = Join-Path $projectRoot 'VALIDATION.md'
    if (Test-Path -LiteralPath $taskValidation -PathType Leaf) {
        # The same record is readable from the project and the standalone output.
        $taskValidationText = (Get-Content -LiteralPath $taskValidation -Raw).Replace('](runs/', '](../../runs/').Replace('](dist/AutoHSR/', '](')
        Set-Content -LiteralPath (Join-Path $taskOutputDirectory 'VALIDATION.md') -Value $taskValidationText -Encoding UTF8
    }
    Write-Host "Build complete: $(Join-Path $taskOutputDirectory 'AutoHSR.exe')"
} finally {
    if ($taskBackupDirectory) {
        New-Item -ItemType Directory -Path $taskOutputDirectory -Force | Out-Null
        foreach ($taskSavedItem in Get-ChildItem -LiteralPath $taskBackupDirectory -Force) {
            Copy-Item -LiteralPath $taskSavedItem.FullName -Destination $taskOutputDirectory -Recurse -Force
        }
        Write-Host "Local settings and records preserved in $taskBackupDirectory and restored to output."
    }
    Pop-Location
}
