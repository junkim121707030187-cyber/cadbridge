param([string]$PythonExe = 'python')
$ErrorActionPreference = 'Stop'
$prototypeRoot = $PSScriptRoot
$runtimeRoot = Join-Path $prototypeRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$environmentPython = Join-Path $runtimeRoot 'python-env/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $environmentPython)) {
    & $PythonExe -m venv (Join-Path $runtimeRoot 'python-env')
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
}
& $environmentPython -m pip install -r (Join-Path $prototypeRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency setup failed.' }
$freecadFolder = Join-Path $runtimeRoot 'FreeCAD_1.1.4-Windows-x86_64-py311'
if (-not (Test-Path -LiteralPath (Join-Path $freecadFolder 'FreeCADCmd.exe'))) {
    $archivePath = Join-Path $runtimeRoot 'FreeCAD_1.1.4-Windows-x86_64-py311.7z'
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri 'https://github.com/FreeCAD/FreeCAD/releases/download/1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311.7z' -OutFile $archivePath
    $expectedHash = '4828741fc91ee37fafcdb97a1abacb18b04ba451ac4372d9ff7a7349b36f4d6d'
    if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
        throw 'Official FreeCAD archive hash mismatch.'
    }
    & tar -xf $archivePath -C $runtimeRoot
    if ($LASTEXITCODE -ne 0) { throw 'FreeCAD extraction failed.' }
}
Write-Output 'CADBridge is ready. Double-click Start.cmd.'
