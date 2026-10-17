# Crea un acceso directo de inicio para el usuario actual; no requiere administrador.
[CmdletBinding()]
param(
    [switch]$Instalar,
    [string]$CarpetaInicio,
    [string]$Pythonw
)
$ErrorActionPreference = 'Stop'
if (-not $CarpetaInicio) { $CarpetaInicio = [Environment]::GetFolderPath('Startup') }
if (-not $Pythonw) {
    $pythonRuta = & py -3 -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0) { throw 'No se encontró Python 3.' }
    $Pythonw = Join-Path (Split-Path -Parent $pythonRuta) 'pythonw.exe'
}
$Pythonw = [IO.Path]::GetFullPath($Pythonw)
$lanzador = Join-Path $PSScriptRoot 'iniciar_bandeja_windows.py'
if (-not (Test-Path -LiteralPath $Pythonw -PathType Leaf)) { throw 'No se encontró pythonw.exe.' }
if (-not (Test-Path -LiteralPath $lanzador -PathType Leaf)) { throw 'Falta el lanzador de Lucie.' }
if (-not (Test-Path -LiteralPath $CarpetaInicio -PathType Container)) { throw 'La carpeta Inicio no existe.' }
$destinoInicio = Join-Path ([IO.Path]::GetFullPath($CarpetaInicio)) 'Lucie.lnk'
$argumentos = '"' + $lanzador + '" --sin-navegador'
Write-Output "Inicio automatico: $destinoInicio"
Write-Output "Programa: $Pythonw"
Write-Output "Argumentos: $argumentos"
if (-not $Instalar) { Write-Output 'Simulacion. Para habilitarlo, ejecutar con -Instalar.'; return }
$shellLucie = New-Object -ComObject WScript.Shell
$accesoLucie = $shellLucie.CreateShortcut($destinoInicio)
if (Test-Path -LiteralPath $destinoInicio) {
    if ($accesoLucie.TargetPath -eq $Pythonw -and $accesoLucie.Arguments -eq $argumentos -and $accesoLucie.WorkingDirectory -eq $PSScriptRoot) {
        Write-Output 'Lucie ya tiene este inicio automatico. No se modifico el acceso directo.'
        return
    }
    throw 'Ya existe un acceso directo Lucie distinto. Se conserva sin sobrescribir.'
}
$accesoLucie.TargetPath = $Pythonw
$accesoLucie.Arguments = $argumentos
$accesoLucie.WorkingDirectory = $PSScriptRoot
$accesoLucie.WindowStyle = 7
$accesoLucie.Description = 'Lucie - Inicio automatico e icono junto al reloj'
$accesoLucie.IconLocation = "$Pythonw,0"
# Reservar exclusivamente el destino; conservarlo si falla la creación del .lnk.
$reservaLucie = [IO.File]::Open($destinoInicio, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
$reservaLucie.Dispose()
$accesoLucie.Save()
Write-Output 'Inicio automatico de Lucie habilitado para el usuario actual.'
