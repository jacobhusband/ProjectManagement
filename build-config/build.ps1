$ErrorActionPreference = "Stop"

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    $global:LASTEXITCODE = 0
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Assert-PathExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not (Test-Path $Path)) {
        throw $Message
    }
}

function Test-PythonImports {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,
        [Parameter(Mandatory = $true)]
        [string[]]$Modules
    )

    $quotedModules = $Modules | ForEach-Object { "'$_'" }
    $importScript = "import importlib.util, sys; missing = [name for name in [" + ($quotedModules -join ", ") + "] if importlib.util.find_spec(name) is None]; sys.exit(0 if not missing else 1)"

    $global:LASTEXITCODE = 0
    & $PythonPath -c $importScript 1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

function Ensure-HeifBuildDependencies {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,
        [Parameter(Mandatory = $true)]
        [string]$RequirementsPath
    )

    $heifModules = @("pillow_heif", "_pillow_heif")
    Write-Host "Checking HEIF build dependencies in .venv..." -ForegroundColor Gray
    if (Test-PythonImports -PythonPath $PythonPath -Modules $heifModules) {
        Write-Host "HEIF build dependencies already available in .venv." -ForegroundColor Gray
        return
    }

    Write-Host "Missing HEIF build dependencies in .venv. Installing from requirements.txt..." -ForegroundColor Yellow
    Invoke-CheckedCommand -Description "pip install -r requirements.txt" -Command {
        & $PythonPath -m pip install -r $RequirementsPath
    }

    if (-not (Test-PythonImports -PythonPath $PythonPath -Modules $heifModules)) {
        throw "HEIF build dependencies are still unavailable after installing $RequirementsPath."
    }

    Write-Host "HEIF build dependencies repaired in .venv." -ForegroundColor Green
}

function Test-PyInstallerArchiveContains {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath,
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,
        [Parameter(Mandatory = $true)]
        [string]$Pattern
    )

    $global:LASTEXITCODE = 0
    $archiveOutput = & $PythonPath -m PyInstaller.utils.cliutils.archive_viewer $ArchivePath -r -b 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to inspect PyInstaller archive at $ArchivePath."
    }

    return [bool]($archiveOutput | Select-String -Pattern $Pattern -Quiet)
}

function Ensure-WebView2Bootstrapper {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    # Setup embeds this small Microsoft installer and runs it on PCs that lack the
    # WebView2 Runtime (see build-config\setup.iss). Reuse a copy from an earlier build.
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $Path -Parent) | Out-Null
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $partialPath = "$Path.download"
        # Microsoft's permanent link to the current Evergreen bootstrapper (about 2 MB).
        Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $partialPath -UseBasicParsing
        Move-Item -LiteralPath $partialPath -Destination $Path -Force
    }

    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "O=Microsoft Corporation") {
        Remove-Item -LiteralPath $Path -Force
        throw "The WebView2 bootstrapper is not signed by Microsoft Corporation (signature status: $($signature.Status)). It was deleted; run the build again."
    }
}

try {
    Write-Host "###################################" -ForegroundColor Cyan
    Write-Host "#      Building ACIES Scheduler     #" -ForegroundColor Cyan
    Write-Host "###################################" -ForegroundColor Cyan

    # Pin the build to the repo-local virtualenv so editor-integrated shells do not change behavior.
    $projectRoot = Split-Path $PSScriptRoot -Parent
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $requirementsPath = Join-Path $projectRoot "requirements.txt"
    $pyInstallerSpecPath = Join-Path $projectRoot "build-config\ACIES Scheduler.spec"
    $envPath = Join-Path $projectRoot ".env"
    Assert-PathExists -Path $venvPython -Message "Repo-local Python interpreter not found at $venvPython. Create or refresh .venv before building."
    Assert-PathExists -Path $requirementsPath -Message "requirements.txt not found at $requirementsPath."
    Assert-PathExists -Path $pyInstallerSpecPath -Message "PyInstaller spec not found at $pyInstallerSpecPath."
    Assert-PathExists -Path $envPath -Message "Required build configuration file not found at $envPath. Copy .env.example to .env, fill in the required values, and rebuild."
    Write-Host "Using Python: $venvPython" -ForegroundColor Gray
    Write-Host "Using PyInstaller spec: $pyInstallerSpecPath" -ForegroundColor Gray
    Ensure-HeifBuildDependencies -PythonPath $venvPython -RequirementsPath $requirementsPath
    if (-not (Test-PythonImports -PythonPath $venvPython -Modules @("numpy", "cv2"))) {
        Write-Host "Missing Symbol Counter build dependencies. Installing from requirements.txt..." -ForegroundColor Yellow
        Invoke-CheckedCommand -Description "pip install -r requirements.txt" -Command {
            & $venvPython -m pip install -r $requirementsPath
        }
    }
    if (-not (Test-PythonImports -PythonPath $venvPython -Modules @("numpy", "cv2"))) {
        throw "Symbol Counter build dependencies (numpy and cv2) are unavailable in .venv."
    }
    Invoke-CheckedCommand -Description "PyInstaller availability check" -Command { & $venvPython -m PyInstaller --version | Out-Null }

    $wireSizerDir = Join-Path $projectRoot "WireSizerApplication"
    $wireSizerPackageJson = Join-Path $wireSizerDir "package.json"
    $wireSizerDist = Join-Path $wireSizerDir "dist"
    $wireSizerIndex = Join-Path $wireSizerDist "index.html"
    $projectPagesEditorDir = Join-Path $projectRoot "project-pages-editor"
    $projectPagesEditorPackageJson = Join-Path $projectPagesEditorDir "package.json"
    $projectPagesEditorDist = Join-Path $projectPagesEditorDir "dist"
    $projectPagesEditorBundle = Join-Path $projectPagesEditorDist "project-pages-editor.js"
    Assert-PathExists -Path $wireSizerDir -Message "WireSizerApplication folder not found at $wireSizerDir."
    Assert-PathExists -Path $wireSizerPackageJson -Message "Wire Sizer package.json not found at $wireSizerPackageJson."
    Assert-PathExists -Path $projectPagesEditorDir -Message "Project Pages editor folder not found at $projectPagesEditorDir."
    Assert-PathExists -Path $projectPagesEditorPackageJson -Message "Project Pages editor package.json not found at $projectPagesEditorPackageJson."

    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npmCmd) {
        throw "npm not found on PATH. Install Node.js/npm before building."
    }
    $npmExecutable = $npmCmd.Source

    Write-Host "`n[1/3] Building Wire Sizer frontend..." -ForegroundColor Yellow
    Write-Host "Using npm: $npmExecutable" -ForegroundColor Gray
    Push-Location $wireSizerDir
    try {
        if (-not (Test-Path "node_modules")) {
            Invoke-CheckedCommand -Description "npm install" -Command { & $npmExecutable install }
        }
        Invoke-CheckedCommand -Description "npm run build" -Command { & $npmExecutable run build }
    } finally {
        Pop-Location
    }
    Assert-PathExists -Path $wireSizerDist -Message "Wire Sizer build completed without producing $wireSizerDist."
    Assert-PathExists -Path $wireSizerIndex -Message "Wire Sizer build output is missing $wireSizerIndex."

    Write-Host "`n[1b/3] Building Project Pages editor frontend..." -ForegroundColor Yellow
    Push-Location $projectPagesEditorDir
    try {
        if (-not (Test-Path "node_modules")) {
            Invoke-CheckedCommand -Description "npm install" -Command { & $npmExecutable install }
        }
        Invoke-CheckedCommand -Description "npm run build" -Command { & $npmExecutable run build }
    } finally {
        Pop-Location
    }
    Assert-PathExists -Path $projectPagesEditorDist -Message "Project Pages editor build completed without producing $projectPagesEditorDist."
    Assert-PathExists -Path $projectPagesEditorBundle -Message "Project Pages editor build output is missing $projectPagesEditorBundle."

    Write-Host "`n[2/3] Bundling application with PyInstaller..." -ForegroundColor Yellow

    $bundleOutput = Join-Path $projectRoot "dist\ACIES Scheduler"
    $bundleInternal = Join-Path $bundleOutput "_internal"
    $setupOutput = Join-Path $projectRoot "dist\setup"
    foreach ($path in @($bundleOutput, $setupOutput)) {
        if (Test-Path $path) {
            Write-Host "Cleaning $path" -ForegroundColor Gray
            Remove-Item -Recurse -Force $path
        }
    }

    $versionPath = Join-Path $projectRoot "VERSION"
    Assert-PathExists -Path $versionPath -Message "VERSION file not found at $versionPath."
    $appVersion = (Get-Content -Raw $versionPath).Trim()
    if (-not $appVersion) {
        throw "VERSION file is empty."
    }

    Push-Location $projectRoot
    try {
        $pyInstallerWorkPath = Join-Path $projectRoot "build\pyinstaller"
        $pyInstallerDistPath = Join-Path $projectRoot "dist"
        $pyInstallerArgs = @(
            "--noconfirm", "--clean",
            "--distpath", $pyInstallerDistPath,
            "--workpath", $pyInstallerWorkPath,
            $pyInstallerSpecPath
        )

        Invoke-CheckedCommand -Description "PyInstaller build" -Command { & $venvPython -m PyInstaller $pyInstallerArgs }
    } finally {
        Pop-Location
    }

    $expectedBundleFiles = @(
        (Join-Path $bundleOutput "ACIES Scheduler.exe"),
        # The console helper the publish script runs its PDF steps with (no system Python needed).
        (Join-Path $bundleOutput "acies-pdf-tools.exe"),
        (Join-Path $bundleInternal "scripts\AutoCadDiscovery.ps1"),
        (Join-Path $bundleInternal "index.html"),
        (Join-Path $bundleInternal "styles.css"),
        (Join-Path $bundleInternal "industry.css"),
        (Join-Path $bundleInternal "modern-workspace.css"),
        (Join-Path $bundleInternal "deliverables-workspace.css"),
        (Join-Path $bundleInternal "assets\acies-modern-logo.png"),
        (Join-Path $bundleInternal "industry-projects.js"),
        (Join-Path $bundleInternal "industry-shell.js"),
        (Join-Path $bundleInternal "script.js"),
        (Join-Path $bundleInternal "symbol_counter.css"),
        (Join-Path $bundleInternal "symbol_counter_ui.js"),
        (Join-Path $bundleInternal "vendor\chart.umd.min.js"),
        (Join-Path $bundleInternal "CircuitBreakerAI\ElectricalPanels\Template.xlsx"),
        (Join-Path $bundleInternal "WireSizerApplication\dist\index.html"),
        (Join-Path $bundleInternal "project-pages-editor\dist\project-pages-editor.js"),
        (Join-Path $bundleInternal "scripts\shrink_pdf.py")
    )
    foreach ($expectedPath in $expectedBundleFiles) {
        Assert-PathExists -Path $expectedPath -Message "PyInstaller bundle is missing expected output: $expectedPath"
    }

    # With no arguments the strip helper prints its usage and exits 2. Reaching that point
    # proves the bundled helper starts and can import PyMuPDF; a broken bundle exits 1.
    $pdfHelperExecutable = Join-Path $bundleOutput "acies-pdf-tools.exe"
    # The usage text goes to stderr, which Windows PowerShell 5.1 turns into a terminating
    # error while ErrorActionPreference is Stop, so relax it just for this call.
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $global:LASTEXITCODE = 0
        $pdfHelperOutput = (& $pdfHelperExecutable "strip_pdf_layers.py" 2>&1 | Out-String)
        $pdfHelperExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($pdfHelperExitCode -ne 2 -or $pdfHelperOutput -notmatch "Usage: python strip_pdf_layers.py") {
        throw "The bundled PDF helper did not start correctly (exit code $pdfHelperExitCode): $pdfHelperOutput"
    }
    Write-Host "Verified bundled PDF helper: $pdfHelperExecutable" -ForegroundColor Gray

    $bundleExecutable = Join-Path $bundleOutput "ACIES Scheduler.exe"
    $heifPackagePath = Join-Path $bundleInternal "pillow_heif"
    $heifPackageBundled = (Test-Path $heifPackagePath) -or (Test-PyInstallerArchiveContains -PythonPath $venvPython -ArchivePath $bundleExecutable -Pattern "^\s*pillow_heif($|\.)")
    if (-not $heifPackageBundled) {
        throw "PyInstaller bundle is missing the pillow_heif package in $bundleOutput."
    }

    $heifNativeModule = Get-ChildItem -Path $bundleInternal -Filter "_pillow_heif*.pyd" -File -Recurse | Select-Object -First 1
    if (-not $heifNativeModule) {
        throw "PyInstaller bundle is missing the HEIF native module (_pillow_heif*.pyd) in $bundleInternal."
    }

    Write-Host "Verified bundled HEIF runtime: $($heifNativeModule.FullName)" -ForegroundColor Gray

    Write-Host "`n[3/3] Creating installer with Inno Setup..." -ForegroundColor Yellow

    $possiblePaths = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles(x86)\Inno Setup 6\iscc.exe",
        "$env:ProgramFiles\Inno Setup 6\iscc.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\iscc.exe"
    )

    $isccPath = $null
    foreach ($path in $possiblePaths) {
        if (Test-Path $path) {
            $isccPath = $path
            break
        }
    }

    if (-not $isccPath) {
        throw "Inno Setup Compiler (iscc.exe) not found. Checked paths: $($possiblePaths -join ', ')"
    }

    Write-Host "Found Inno Setup at: $isccPath" -ForegroundColor Gray

    Write-Host "Fetching the WebView2 Runtime bootstrapper for the installer..." -ForegroundColor Gray
    Ensure-WebView2Bootstrapper -Path (Join-Path $projectRoot "build\webview2\MicrosoftEdgeWebview2Setup.exe")
    Invoke-CheckedCommand -Description "Inno Setup compilation" -Command {
        & $isccPath "/DMyAppVersion=$appVersion" (Join-Path $PSScriptRoot "setup.iss")
    }

    $installerPath = Join-Path $setupOutput "acies-scheduler-setup.exe"
    Assert-PathExists -Path $installerPath -Message "Inno Setup finished without producing $installerPath."

    Write-Host "`n###################################" -ForegroundColor Green
    Write-Host "#      Build process complete!      #" -ForegroundColor Green
    Write-Host "###################################" -ForegroundColor Green
    Write-Host "Installer created at: dist\setup\acies-scheduler-setup.exe"
} catch {
    Write-Error $_
    exit 1
}
