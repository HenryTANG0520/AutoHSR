[CmdletBinding()]
param(
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$taskVenvDirectory = Join-Path $projectRoot '.venv'
$taskVenvPython = Join-Path $taskVenvDirectory 'Scripts\python.exe'
$taskRequirements = Join-Path $projectRoot 'requirements.txt'

function Resolve-SupportedPython {
    param(
        [Parameter(Mandatory = $true)][string]$Candidate,
        [string[]]$Arguments = @()
    )
    try {
        $taskProbe = @(& $Candidate @Arguments -c 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null)
        if ($LASTEXITCODE -eq 0 -and $taskProbe.Count -gt 0) {
            $taskExecutable = [string]$taskProbe[-1]
            if (Test-Path -LiteralPath $taskExecutable -PathType Leaf) {
                return $taskExecutable
            }
        }
    } catch {
        # Continue discovery when a launcher or an application alias is unusable.
    }
    return $null
}

if (-not (Test-Path -LiteralPath $taskRequirements -PathType Leaf)) {
    throw 'requirements.txt was not found beside setup.ps1.'
}

if ($PythonPath) {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "PythonPath does not exist: $PythonPath"
    }
    $taskPython = Resolve-SupportedPython -Candidate (Get-Item -LiteralPath $PythonPath).FullName
    if (-not $taskPython) {
        throw 'PythonPath must point to a working Python 3.10 or newer interpreter.'
    }
} else {
    $taskPython = $null
    $taskPyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($taskPyLauncher) {
        $taskPython = Resolve-SupportedPython -Candidate $taskPyLauncher.Source -Arguments @('-3')
    }
    foreach ($taskCommandName in @('python.exe', 'python3.exe')) {
        if ($taskPython) { break }
        $taskCommand = Get-Command $taskCommandName -ErrorAction SilentlyContinue
        if ($taskCommand) {
            $taskPython = Resolve-SupportedPython -Candidate $taskCommand.Source
        }
    }
    if (-not $taskPython) {
        throw 'Python 3.10+ was not found. Install Python or supply -PythonPath "C:\path\to\python.exe".'
    }
}

Write-Host "Python: $taskPython"
if (-not (Test-Path -LiteralPath $taskVenvPython -PathType Leaf)) {
    Write-Host 'Creating the project virtual environment...'
    & $taskPython -m venv $taskVenvDirectory
    if ($LASTEXITCODE -ne 0) {
        throw 'Virtual environment creation failed. Use a Python runtime that includes venv and pip.'
    }
} else {
    Write-Host 'Keeping the existing project virtual environment.'
}

if (-not (Resolve-SupportedPython -Candidate $taskVenvPython)) {
    throw 'The existing .venv is unusable or older than Python 3.10. Repair or replace it before retrying.'
}

& $taskVenvPython -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(''pip'') else 1)'
if ($LASTEXITCODE -ne 0) {
    & $taskVenvPython -m ensurepip
    if ($LASTEXITCODE -ne 0) { throw 'pip is unavailable in the project virtual environment.' }
}

Write-Host 'Installing AutoHSR dependencies into .venv...'
& $taskVenvPython -m pip install --disable-pip-version-check -r $taskRequirements
if ($LASTEXITCODE -ne 0) {
    throw 'Dependency installation failed. Check the Python version, network connection, and pip output.'
}
Write-Host 'Setup complete. Double-click Start-AutoHSR.cmd to open the GUI.'
