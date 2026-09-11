$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$BuildLog = Join-Path $PSScriptRoot "build.log"
if (-not (Test-Path $BuildLog)) { New-Item -ItemType File -Path $BuildLog -Force | Out-Null }
Start-Transcript -Path $BuildLog -Append | Out-Null
$ExitCode = 0

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$false)][string[]]$Arguments = @()
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("Command failed with exit code {0}: {1} {2}" -f $LASTEXITCODE, $FilePath, ($Arguments -join ' '))
    }
}

try {
    Write-Host "Building autojobs for Windows..." -ForegroundColor Cyan
    Write-Host "Full build output is being saved to: $BuildLog" -ForegroundColor DarkGray

    if (Get-Command py -ErrorAction SilentlyContinue) {
        $Python = "py"
        $PythonArgs = @("-3.13")
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $Python = "python"
        $PythonArgs = @()
    } else {
        throw "Python was not found. Install Python 3.13 (64-bit) on the BUILD computer and run this script again. Python is NOT required on computers that only run the finished autojobs.exe."
    }

    Invoke-Checked -FilePath $Python -Arguments ($PythonArgs + @("-m", "venv", ".venv"))
    $VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "-r", "requirements-dev.txt")
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pytest", "-q")

    # Never leave stale artifacts from an older build inside the portable folder.
    $Dist = Join-Path $PSScriptRoot "dist"
    if (Test-Path $Dist) { Remove-Item $Dist -Recurse -Force }
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "PyInstaller", "--noconfirm", "--clean", "autojobs.spec")

    $Exe = Join-Path $Dist "autojobs.exe"
    if (-not (Test-Path $Exe)) {
        throw "Build finished without the expected executable: $Exe"
    }

    # External/editable files intentionally live beside autojobs.exe. Runtime
    # paths are resolved from the executable directory, so this folder is portable.
    $PortableFiles = @("themes.json", "README.txt", "prompt.txt", "answer-profile-template.json")
    foreach ($File in $PortableFiles) {
        $Source = Join-Path $PSScriptRoot $File
        if (-not (Test-Path $Source)) { throw "Required portable file is missing: $Source" }
        Copy-Item $Source (Join-Path $Dist $File) -Force
    }

    $BuildInfo = @"
autojobs 2.9.2 portable Windows build

This folder is self-contained for normal use.
Python is NOT required on the destination computer.
Google Chrome must be installed.
Internet access may be required the first time Selenium Manager resolves a compatible ChromeDriver.
Keep autojobs.exe, themes.json, README.txt, prompt.txt and answer-profile-template.json together.
"@
    Set-Content -Path (Join-Path $Dist "BUILD_INFO.txt") -Value $BuildInfo -Encoding UTF8

    # Create a ready-to-share ZIP outside dist, so users can also zip the contents
    # of dist manually without nesting an old release archive.
    $ReleaseDir = Join-Path $PSScriptRoot "release"
    if (-not (Test-Path $ReleaseDir)) { New-Item -ItemType Directory -Path $ReleaseDir | Out-Null }
    $PortableZip = Join-Path $ReleaseDir "autojobs-v2.9.2-portable-win64.zip"
    if (Test-Path $PortableZip) { Remove-Item $PortableZip -Force }
    Compress-Archive -Path (Join-Path $Dist "*") -DestinationPath $PortableZip -CompressionLevel Optimal

    Write-Host ""
    Write-Host "Portable build complete:" -ForegroundColor Green
    Write-Host $Exe
    Write-Host "Portable ZIP:" -ForegroundColor Green
    Write-Host $PortableZip
    Write-Host "Destination computers do not need Python; they do need Google Chrome." -ForegroundColor Green

    # Build a real per-user Windows Setup when Inno Setup 6 is available.
    $IsccCandidates = @(@(
        (Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Join-Path $env:USERPROFILE "AppData\Local\Programs\Inno Setup 6\ISCC.exe"),
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)

    if ($IsccCandidates.Count -gt 0) {
        $Iscc = $IsccCandidates[0]
        Invoke-Checked -FilePath $Iscc -Arguments @((Join-Path $PSScriptRoot "installer\autojobs.iss"))
        $SetupExe = Join-Path $PSScriptRoot "installer-output\autojobs-Setup.exe"
        if (-not (Test-Path $SetupExe)) {
            throw "Inno Setup finished without the expected installer: $SetupExe"
        }
        Write-Host "Windows Setup complete:" -ForegroundColor Green
        Write-Host $SetupExe
    } else {
        Write-Host "Inno Setup 6 was not found. Portable autojobs.exe was built successfully." -ForegroundColor Yellow
        Write-Host "Install Inno Setup 6 on the BUILD computer if you also want autojobs-Setup.exe." -ForegroundColor Yellow
    }

    $WarnFile = Join-Path $PSScriptRoot "build\autojobs\warn-autojobs.txt"
    if (Test-Path $WarnFile) {
        Write-Host "PyInstaller diagnostic warnings (usually optional imports): $WarnFile" -ForegroundColor DarkYellow
    }
    Write-Host "Build log: $BuildLog" -ForegroundColor Cyan
}
catch {
    $ExitCode = 1
    Write-Host ""
    Write-Host "BUILD FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Full build log: $BuildLog" -ForegroundColor Yellow
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}

exit $ExitCode
