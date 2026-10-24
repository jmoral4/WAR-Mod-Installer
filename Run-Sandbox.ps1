$ErrorActionPreference = 'Stop'
$installerBuild = @('dist\WAR-Mod-Installer.exe', 'dist\updated\WAR-Mod-Installer.exe') |
    ForEach-Object { Join-Path $PSScriptRoot $_ } |
    Where-Object { Test-Path -LiteralPath $_ } |
    ForEach-Object { Get-Item -LiteralPath $_ } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($installerBuild) {
    & $installerBuild.FullName --sandbox-root $PSScriptRoot
} else {
    Push-Location $PSScriptRoot
    try {
        python -m war_mod_installer --sandbox-root $PSScriptRoot
    } finally {
        Pop-Location
    }
}
