<#
Checks what a new user gets on a clean Windows PC: installs ACIES Scheduler with its
installer, then tries the things that used to fail on PCs without Python, AutoCAD or
the WebView2 Runtime, and finally uninstalls.

  smoke-test-installer.ps1 -InstallerPath .\acies-scheduler-setup.exe
      Installs, tests and uninstalls. Run this only on a throwaway machine or VM: it uses
      the real Setup, so on a PC that already has ACIES Scheduler it would replace that install.
      The installer-smoke workflow runs it on a fresh GitHub Windows VM.

  smoke-test-installer.ps1 -AppDir "dist\ACIES Scheduler"
      Tests an app folder that is already unpacked (a PyInstaller build) and skips the
      install and uninstall steps. Safe on a development PC.

The app itself always runs against a scratch user profile, so it never touches real data.
Exits 1 if a required check fails. On GitHub Actions each result is also written as an
annotation, because the job log needs a sign-in to read.
#>
[CmdletBinding()]
param(
    [string]$InstallerPath,
    [string]$AppDir,
    [int]$BootTimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$results = New-Object System.Collections.Generic.List[object]
$onActions = [bool]$env:GITHUB_ACTIONS
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("acies-smoke-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $work | Out-Null

function Write-Annotation {
    param([string]$Level, [string]$Title, [string]$Message)
    if (-not $onActions) { return }
    # Workflow commands are one line, so % and line breaks in the text must be escaped.
    $encodedTitle = $Title.Replace("%", "%25").Replace("`r", "%0D").Replace("`n", "%0A").Replace(":", "%3A").Replace(",", "%2C")
    $encodedMessage = $Message.Replace("%", "%25").Replace("`r", "%0D").Replace("`n", "%0A")
    Write-Host "::$Level title=$encodedTitle::$encodedMessage"
}

function Add-Result {
    param([string]$Name, [bool]$Passed, [string]$Detail = "", [switch]$Informational)
    $results.Add([pscustomobject]@{ Name = $Name; Passed = $Passed; Detail = $Detail; Informational = [bool]$Informational })
    $mark = if ($Informational) { "INFO" } elseif ($Passed) { "PASS" } else { "FAIL" }
    Write-Host ("[{0}] {1}{2}" -f $mark, $Name, $(if ($Detail) { " - $Detail" } else { "" }))
}

function Get-WebView2Version {
    $guids = @("{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}", "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
        "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}", "{65C35B14-6C1D-4122-AC46-7148CC9D6497}")
    $bases = @("HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients", "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients")
    foreach ($guid in $guids) {
        foreach ($base in $bases) {
            $value = (Get-ItemProperty -LiteralPath "$base\$guid" -Name pv -ErrorAction SilentlyContinue).pv
            if ($value -and $value -ne "0.0.0.0") { return [string]$value }
        }
    }
    return ""
}

function Get-PathWithoutPython {
    # What a new user's PATH looks like: no Python, and no Microsoft Store "python" stub either.
    $kept = foreach ($entry in ($env:PATH -split ";")) {
        if ([string]::IsNullOrWhiteSpace($entry)) { continue }
        if ($entry -match "WindowsApps") { continue }
        if ((Test-Path -LiteralPath (Join-Path $entry "python.exe")) -or (Test-Path -LiteralPath (Join-Path $entry "py.exe"))) { continue }
        $entry
    }
    return ($kept -join ";")
}

function New-TestPdf {
    param([string]$Path, [int]$Pages = 1)
    $kids = (1..$Pages | ForEach-Object { "$(2 + $_) 0 R" }) -join " "
    $text = "%PDF-1.4`n1 0 obj`n<< /Type /Catalog /Pages 2 0 R >>`nendobj`n2 0 obj`n<< /Type /Pages /Kids [$kids] /Count $Pages >>`nendobj`n"
    for ($i = 1; $i -le $Pages; $i++) {
        $text += "$(2 + $i) 0 obj`n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 2592 3456] >>`nendobj`n"
    }
    $text += "trailer`n<< /Root 1 0 R /Size $(3 + $Pages) >>`n%%EOF`n"
    [System.IO.File]::WriteAllText($Path, $text, [System.Text.Encoding]::ASCII)
}

# Runs a program with the PATH a new user would have and returns its exit code and output.
function Invoke-Clean {
    param([string]$FilePath, [string[]]$Arguments, [int]$TimeoutSeconds = 120)
    $stdout = Join-Path $work ("out-" + [guid]::NewGuid().ToString("N").Substring(0, 6) + ".txt")
    $stderr = "$stdout.err"
    $savedPath = $env:PATH
    $env:PATH = Get-PathWithoutPython
    try {
        $quoted = $Arguments | ForEach-Object { if ($_ -match "\s") { '"' + $_ + '"' } else { $_ } }
        $process = Start-Process -FilePath $FilePath -ArgumentList $quoted -NoNewWindow -PassThru `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        # Windows PowerShell 5.1 reports a blank ExitCode unless the handle is read while the
        # process is still running.
        $null = $process.Handle
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            & taskkill.exe /PID $process.Id /T /F | Out-Null
            return [pscustomobject]@{ ExitCode = -1; Output = "TIMED OUT after $TimeoutSeconds s" }
        }
        $process.WaitForExit()
        $text = ((Get-Content -Raw -LiteralPath $stdout -ErrorAction SilentlyContinue) + (Get-Content -Raw -LiteralPath $stderr -ErrorAction SilentlyContinue))
        return [pscustomobject]@{ ExitCode = $process.ExitCode; Output = [string]$text }
    } finally {
        $env:PATH = $savedPath
    }
}

function Find-Install {
    $keys = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C8DE22A3-3BD3-43F2-8A05-A35631A419D2}_is1",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{C8DE22A3-3BD3-43F2-8A05-A35631A419D2}_is1",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\{C8DE22A3-3BD3-43F2-8A05-A35631A419D2}_is1"
    )
    foreach ($key in $keys) {
        $location = (Get-ItemProperty -LiteralPath $key -Name InstallLocation -ErrorAction SilentlyContinue).InstallLocation
        if ($location) { return [pscustomobject]@{ Key = $key; Dir = $location.TrimEnd("\") } }
    }
    return $null
}

$installedBySetup = $false
$exitCode = 0
try {
    # ---------------------------------------------------------------- environment
    $os = Get-CimInstance Win32_OperatingSystem
    $pythonBefore = [bool](Get-Command python -ErrorAction SilentlyContinue)
    $autocadBefore = (Test-Path "$env:ProgramFiles\Autodesk\AutoCAD *\accoreconsole.exe")
    $webViewBefore = Get-WebView2Version
    $dotNetRelease = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full" -Name Release -ErrorAction SilentlyContinue).Release
    $environment = "$($os.Caption) build $($os.BuildNumber); WebView2 before install: $(if ($webViewBefore) { $webViewBefore } else { 'not installed' }); " +
        ".NET Framework release $dotNetRelease; python on PATH: $pythonBefore; AutoCAD installed: $autocadBefore"
    Add-Result "Test machine" $true $environment -Informational

    # ---------------------------------------------------------------- install
    if ($AppDir) {
        $appDir = (Resolve-Path -LiteralPath $AppDir).Path
        Add-Result "Install" $true "skipped, testing the app folder $appDir" -Informational
    } else {
        if (-not $InstallerPath) { throw "Pass -InstallerPath (to install) or -AppDir (to test an unpacked app)." }
        $setupLog = Join-Path $work "setup.log"
        $setup = Start-Process -FilePath (Resolve-Path -LiteralPath $InstallerPath).Path -Wait -PassThru `
            -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=$setupLog")
        $installedBySetup = $true
        $install = Find-Install
        $appDir = if ($install) { $install.Dir } else { "" }
        $setupText = Get-Content -Raw -LiteralPath $setupLog -ErrorAction SilentlyContinue
        Add-Result "Setup runs silently and registers the app" ($setup.ExitCode -eq 0 -and [bool]$install) "exit code $($setup.ExitCode), install folder: $appDir"
        $needed = $setupText -match "Extracting temporary file: .*MicrosoftEdgeWebview2Setup\.exe"
        Add-Result "Setup handled the WebView2 Runtime" $true $(if ($needed) { "it was missing, so Setup ran Microsoft's bootstrapper" } else { "it was already installed, so Setup left it alone" }) -Informational
    }

    $exe = Join-Path $appDir "ACIES Scheduler.exe"
    $helper = Join-Path $appDir "acies-pdf-tools.exe"
    $scripts = Join-Path $appDir "_internal\scripts"
    $missing = @($exe, $helper, "$scripts\PlotDWGs.ps1", "$scripts\AutoCadDiscovery.ps1", "$appDir\_internal\index.html") | Where-Object { -not (Test-Path -LiteralPath $_) }
    Add-Result "Installed files are all there" ($missing.Count -eq 0) $(if ($missing.Count) { "missing: " + ($missing -join ", ") } else { "app, PDF helper, CAD scripts and web UI" })
    if ($missing.Count) { throw "The install is incomplete, so the remaining checks cannot run." }

    $webViewAfter = Get-WebView2Version
    Add-Result "WebView2 Runtime is present for the app" ([bool]$webViewAfter) $(if ($webViewAfter) { "version $webViewAfter" } else { "not installed after Setup" })

    # ---------------------------------------------------------------- PDF helpers, no Python
    $pdfDir = Join-Path $work "pdf"
    New-Item -ItemType Directory -Force -Path "$pdfDir\Electrical" | Out-Null
    New-TestPdf "$pdfDir\a.pdf" 1
    New-TestPdf "$pdfDir\b.pdf" 2
    Set-Content -LiteralPath "$pdfDir\Electrical\E1.dwg" -Value "x"
    $merge = Invoke-Clean $helper @("$scripts\merge_pdfs.py", "$pdfDir\merged.pdf", "$pdfDir\a.pdf", "$pdfDir\b.pdf")
    $strip = Invoke-Clean $helper @("$scripts\strip_pdf_layers.py", "$pdfDir\merged.pdf")
    $shrink = Invoke-Clean $helper @("$scripts\shrink_pdf.py", "$pdfDir\merged.pdf", "$pdfDir\small.pdf", "50")
    $detect = Invoke-Clean $helper @("$scripts\detect_pdf_size.py", "$pdfDir\Electrical\E1.dwg")
    $stray = Invoke-Clean $helper @("$pdfDir\Electrical\E1.dwg")
    $helperOk = ($merge.ExitCode -eq 0 -and $merge.Output -match "Successfully merged 2 PDF") -and
        ($strip.ExitCode -eq 0) -and ($shrink.ExitCode -eq 0) -and ($detect.ExitCode -eq 0 -and $detect.Output.Trim() -eq "") -and
        ($stray.ExitCode -eq 2)
    $helperDetail = "merge=$($merge.ExitCode) strip=$($strip.ExitCode) shrink=$($shrink.ExitCode) detect=$($detect.ExitCode) (stdout '$($detect.Output.Trim())') refuses other scripts=$($stray.ExitCode)"
    Add-Result "PDF steps work with no Python on PATH" $helperOk $helperDetail
    if (-not $helperOk) { Write-Annotation "error" "PDF helper output" (($merge.Output + "`n" + $strip.Output + "`n" + $shrink.Output + "`n" + $detect.Output).Trim()) }

    # ---------------------------------------------------------------- publish script, no Python
    $env:ACIES_NONINTERACTIVE = "1"
    $env:ACIES_PDF_PYTHON = $helper
    $psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $publish = Invoke-Clean $psExe @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "$scripts\PlotDWGs.ps1") 90
    $env:ACIES_PDF_PYTHON = $null
    $blamesPython = $publish.Output -match "Python executable"
    $expectation = if ($autocadBefore) { "gets past the Python check" } else { "reports that AutoCAD is missing, not Python" }
    $publishOk = (-not $blamesPython) -and ($autocadBefore -or $publish.Output -match "AutoCAD Core Console .* was not found")
    Add-Result "Publish DWGs $expectation" $publishOk ("exit $($publish.ExitCode): " + (($publish.Output -split "`r?`n" | Where-Object { $_ -match "PROGRESS" } | Select-Object -First 3) -join " | "))
    if (-not $publishOk) { Write-Annotation "error" "Publish script output" $publish.Output.Trim() }

    # ---------------------------------------------------------------- the app starts
    $profileDir = Join-Path $work "profile"
    New-Item -ItemType Directory -Force -Path "$profileDir\Documents", "$profileDir\AppData\Roaming", "$profileDir\AppData\Local", "$profileDir\Temp" | Out-Null
    $saved = @{ USERPROFILE = $env:USERPROFILE; APPDATA = $env:APPDATA; LOCALAPPDATA = $env:LOCALAPPDATA; TEMP = $env:TEMP; TMP = $env:TMP }
    $env:USERPROFILE = $profileDir; $env:APPDATA = "$profileDir\AppData\Roaming"; $env:LOCALAPPDATA = "$profileDir\AppData\Local"
    $env:TEMP = "$profileDir\Temp"; $env:TMP = "$profileDir\Temp"; $env:ACIES_NONINTERACTIVE = "1"
    $logPath = "$profileDir\Documents\ProjectManagementApp\logs\acies-scheduler.log"
    $app = Start-Process -FilePath $exe -WorkingDirectory $appDir -PassThru
    foreach ($name in $saved.Keys) { Set-Item -Path "Env:$name" -Value $saved[$name] }
    $bootOk = $false; $bootDetail = ""
    $deadline = (Get-Date).AddSeconds($BootTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $log = Get-Content -Raw -LiteralPath $logPath -ErrorAction SilentlyContinue
        if ($log -match "Fetching bundle statuses") { $bootOk = $true; $bootDetail = "the window loaded and the page reached Python"; break }
        if ($log -match "Cannot start:") { $bootDetail = "the app refused to start: " + (($log -split "`r?`n" | Where-Object { $_ -match "Cannot start:" } | Select-Object -First 1)); break }
        if ($app.HasExited) { $bootDetail = "the app exited with code $($app.ExitCode) before the page loaded"; break }
    }
    if (-not $bootOk -and -not $bootDetail) { $bootDetail = "no sign of the page loading after $BootTimeoutSeconds s" }
    $log = Get-Content -Raw -LiteralPath $logPath -ErrorAction SilentlyContinue
    if (-not $app.HasExited) { & taskkill.exe /PID $app.Id /T /F | Out-Null }
    Add-Result "The app starts on this PC" $bootOk $bootDetail
    $critical = $log -match " - CRITICAL - "
    Add-Result "The app log has no critical errors" (-not $critical) $(if ($critical) { "see the log below" } else { "clean" })
    Write-Annotation $(if ($bootOk -and -not $critical) { "notice" } else { "error" }) "App log" $(if ($log) { $log.Trim() } else { "(no log file was written)" })

    # ---------------------------------------------------------------- uninstall
    if ($installedBySetup) {
        $uninstaller = Get-ChildItem -LiteralPath $appDir -Filter "unins*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($uninstaller) {
            $un = Start-Process -FilePath $uninstaller.FullName -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
            Start-Sleep -Seconds 3
            $gone = (-not (Test-Path -LiteralPath $exe)) -and ($null -eq (Find-Install))
            Add-Result "Uninstall removes the app" ($un.ExitCode -eq 0 -and $gone) "exit code $($un.ExitCode)"
        } else {
            Add-Result "Uninstall removes the app" $false "no uninstaller was found in $appDir"
        }
    }
} catch {
    Add-Result "Smoke test ran to the end" $false $_.Exception.Message
} finally {
    $env:ACIES_PDF_PYTHON = $null
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- report
$failed = @($results | Where-Object { -not $_.Passed -and -not $_.Informational })
$lines = foreach ($r in $results) {
    $mark = if ($r.Informational) { "info" } elseif ($r.Passed) { "PASS" } else { "FAIL" }
    "[{0}] {1}: {2}" -f $mark, $r.Name, $r.Detail
}
Write-Host ""
Write-Host ($lines -join "`n")
Write-Annotation $(if ($failed.Count) { "error" } else { "notice" }) "Smoke test: $($results.Count - $failed.Count) of $($results.Count) checks passed" ($lines -join "`n")
if ($env:GITHUB_STEP_SUMMARY) {
    $summary = "### Installer smoke test`n`n" + (($results | ForEach-Object {
        $mark = if ($_.Informational) { "info" } elseif ($_.Passed) { "pass" } else { "**FAIL**" }
        "- $mark - $($_.Name): $($_.Detail)"
    }) -join "`n")
    Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $summary -Encoding utf8
}
if ($failed.Count) { exit 1 }
exit 0
