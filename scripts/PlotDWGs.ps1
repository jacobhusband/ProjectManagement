param(
  [string]$AcadCore,
  $AutoDetectPaperSize = "true",
  $AutoAcceptDetectedPaperSize = "false",
  [int]$ShrinkPercent = 100,
  $StripPdfLayers = "true",
  $RefreshExcelOleLinks = "true",
  [string]$FilesListPath = "",
  [string]$DefaultDirectory = ""
)

function Convert-ToBool {
  param(
    [object]$Value,
    [bool]$DefaultValue = $true
  )
  if ($null -eq $Value) { return $DefaultValue }
  $text = $Value.ToString().Trim()
  if ($text.StartsWith('$')) { $text = $text.Substring(1) }
  switch -Regex ($text) {
    '^(1|true|t|yes|y)$' { return $true }
    '^(0|false|f|no|n)$' { return $false }
    default { return $DefaultValue }
  }
}

# Keep toggle parameters untyped: a [string] constraint would coerce the
# normalized $false back to "False", which is truthy in PowerShell conditions.
$AutoDetectPaperSize = Convert-ToBool $AutoDetectPaperSize $true
$AutoAcceptDetectedPaperSize = Convert-ToBool $AutoAcceptDetectedPaperSize $false
$StripPdfLayers = Convert-ToBool $StripPdfLayers $true
$RefreshExcelOleLinks = Convert-ToBool $RefreshExcelOleLinks $true

function Ensure-WinFormsAssemblies {
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing
}

function Resolve-DialogInitialDirectory {
  param(
    [string]$CandidatePath,
    [string]$FallbackPath = ""
  )

  if ([string]::IsNullOrWhiteSpace($CandidatePath)) { return $FallbackPath }
  $resolvedPath = $CandidatePath.Trim()
  if (Test-Path -Path $resolvedPath -PathType Leaf) {
    $resolvedPath = Split-Path -Path $resolvedPath -Parent
  }
  if (-not [string]::IsNullOrWhiteSpace($resolvedPath) -and (Test-Path -Path $resolvedPath -PathType Container)) {
    return $resolvedPath
  }
  return $FallbackPath
}

function Move-FormToPrimaryScreen {
  param([System.Windows.Forms.Form]$TargetForm)

  if ($null -eq $TargetForm) { return }
  $workingArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
  $x = $workingArea.Left + [Math]::Max(0, [int](($workingArea.Width - $TargetForm.Width) / 2))
  $y = $workingArea.Top + [Math]::Max(0, [int](($workingArea.Height - $TargetForm.Height) / 2))
  $TargetForm.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual
  $TargetForm.Location = New-Object System.Drawing.Point($x, $y)
}

function Show-DwgFileSelectionPrompt {
  # The picker runs inside a hidden-console child process, so a bare
  # OpenFileDialog.ShowDialog() has no owner window and Windows refuses to pull
  # it in front of the app that launched it. The dialog then sits behind the
  # main window while the tool looks frozen. Owning it with a TopMost form keeps
  # it visible and gives the user a taskbar entry to get back to.
  $promptForm = New-Object System.Windows.Forms.Form
  $promptForm.Text = "Select DWG file(s) to plot"
  $promptForm.StartPosition = "Manual"
  $promptForm.Size = New-Object System.Drawing.Size(560, 190)
  $promptForm.MinimumSize = New-Object System.Drawing.Size(560, 190)
  $promptForm.MaximumSize = New-Object System.Drawing.Size(560, 190)
  $promptForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
  $promptForm.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Font
  $promptForm.MaximizeBox = $false
  $promptForm.MinimizeBox = $false
  $promptForm.TopMost = $true
  $promptForm.ShowInTaskbar = $true
  $promptForm.WindowState = [System.Windows.Forms.FormWindowState]::Normal
  Move-FormToPrimaryScreen $promptForm

  $lblPrompt = New-Object System.Windows.Forms.Label
  $lblPrompt.Text = "Choose one or more DWG files to publish. This window stays on top until files are selected or you exit."
  $lblPrompt.Location = New-Object System.Drawing.Point(16, 16)
  $lblPrompt.Size = New-Object System.Drawing.Size(520, 52)
  $lblPrompt.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
  $promptForm.Controls.Add($lblPrompt)

  $btnSelectFiles = New-Object System.Windows.Forms.Button
  $btnSelectFiles.Text = "Select DWG Files..."
  $btnSelectFiles.Size = New-Object System.Drawing.Size(210, 44)
  $btnSelectFiles.Location = New-Object System.Drawing.Point(222, 92)
  $btnSelectFiles.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Right
  $btnSelectFiles.Font = New-Object System.Drawing.Font("Segoe UI", 9.5, [System.Drawing.FontStyle]::Bold)
  $btnSelectFiles.FlatStyle = [System.Windows.Forms.FlatStyle]::System
  $promptForm.Controls.Add($btnSelectFiles)

  $btnExitPrompt = New-Object System.Windows.Forms.Button
  $btnExitPrompt.Text = "Exit"
  $btnExitPrompt.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
  $btnExitPrompt.Size = New-Object System.Drawing.Size(110, 44)
  $btnExitPrompt.Location = New-Object System.Drawing.Point(434, 92)
  $btnExitPrompt.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Right
  $btnExitPrompt.Font = New-Object System.Drawing.Font("Segoe UI", 10)
  $btnExitPrompt.FlatStyle = [System.Windows.Forms.FlatStyle]::System
  $promptForm.Controls.Add($btnExitPrompt)

  $promptForm.CancelButton = $btnExitPrompt
  $promptForm.AcceptButton = $btnSelectFiles

  $dlg = New-Object System.Windows.Forms.OpenFileDialog
  $dlg.Title = "Select DWG file(s) to plot"
  $dlg.Filter = "DWG files (*.dwg)|*.dwg|All files (*.*)|*.*"
  $dlg.Multiselect = $true
  $dlg.CheckFileExists = $true
  $dlg.CheckPathExists = $true
  $dlg.RestoreDirectory = $true
  $dlg.InitialDirectory = Resolve-DialogInitialDirectory `
    -CandidatePath $DefaultDirectory `
    -FallbackPath ([Environment]::GetFolderPath("Desktop"))

  $btnSelectFiles.add_Click({
      $promptForm.TopMost = $true
      $promptForm.Activate()
      $result = $dlg.ShowDialog($promptForm)
      if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $dlg.FileNames.Count -gt 0) {
        $promptForm.Tag = [string[]]$dlg.FileNames
        $promptForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $promptForm.Close()
        return
      }
      $promptForm.TopMost = $true
      $promptForm.Activate()
      $promptForm.BringToFront()
    })

  $promptForm.add_Shown({
      $promptForm.Activate()
      $promptForm.BringToFront()
      $btnSelectFiles.PerformClick()
    })

  # Keep this prompt from being minimized so it remains actionable.
  $promptForm.add_Resize({
      if ($promptForm.WindowState -eq [System.Windows.Forms.FormWindowState]::Minimized) {
        $promptForm.WindowState = [System.Windows.Forms.FormWindowState]::Normal
        Move-FormToPrimaryScreen $promptForm
        $promptForm.Activate()
        $promptForm.BringToFront()
      }
    })

  $promptResult = $promptForm.ShowDialog()
  if ($promptResult -eq [System.Windows.Forms.DialogResult]::OK) {
    $selectedFiles = @($promptForm.Tag)
    if ($selectedFiles.Count -gt 0) {
      return $selectedFiles
    }
  }
  return $null
}

function Convert-ToLispPath {
  param([string]$PathValue)
  if ([string]::IsNullOrWhiteSpace($PathValue)) { return "" }
  return ($PathValue -replace '\\', '/')
}

function Convert-ToLispQuotedList {
  param([string[]]$Values)
  $cleanValues = @(
    $Values |
      Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
      Select-Object -Unique
  )
  if ($cleanValues.Count -eq 0) {
    return '"ctextapp.arx"'
  }
  return ($cleanValues | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }) -join " "
}

function Convert-ToSafeFileStem {
  param([string]$Value)

  if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
  $safeStem = $Value.Trim()
  foreach ($invalidChar in [System.IO.Path]::GetInvalidFileNameChars()) {
    $safeStem = $safeStem.Replace([string]$invalidChar, " ")
  }
  $safeStem = ($safeStem -replace '\s+', ' ').Trim()
  return $safeStem.TrimEnd([char[]]@('.', ' '))
}

function Get-MaxPdfFileNameLengthForDirectory {
  param(
    [string]$OutputDirectory,
    [int]$MaxFullPathLength = 240
  )

  if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { return 0 }
  $normalizedDirectory = $OutputDirectory.TrimEnd([char[]]@('\', '/'))
  $maxFileNameLength = $MaxFullPathLength - $normalizedDirectory.Length - 1
  if ($maxFileNameLength -lt 1) { return 1 }
  return $maxFileNameLength
}

function Convert-ToSafePdfFileName {
  param(
    [string]$BaseName,
    [string]$FallbackName = "combined.pdf",
    [int]$MaxFileNameLength = 0,
    [string]$PreserveSuffix = ""
  )

  if ([string]::IsNullOrWhiteSpace($BaseName)) { return $FallbackName }
  $safeName = Convert-ToSafeFileStem -Value $BaseName
  if ([string]::IsNullOrWhiteSpace($safeName)) { return $FallbackName }

  $extension = ".pdf"
  $fileName = "$safeName$extension"
  if ($MaxFileNameLength -gt 0 -and $fileName.Length -gt $MaxFileNameLength) {
    $safeSuffix = Convert-ToSafeFileStem -Value $PreserveSuffix
    $suffixPart = ""
    $prefixPart = $safeName

    if (-not [string]::IsNullOrWhiteSpace($safeSuffix)) {
      $suffixPart = " - $safeSuffix"
      if ($prefixPart.EndsWith($suffixPart, [System.StringComparison]::OrdinalIgnoreCase)) {
        $prefixPart = $prefixPart.Substring(0, $prefixPart.Length - $suffixPart.Length)
        $prefixPart = $prefixPart.TrimEnd([char[]]@('.', ' ', '-'))
      }
    }

    $ellipsis = "..."
    $reservedLength = $ellipsis.Length + $suffixPart.Length + $extension.Length
    $maxPrefixLength = $MaxFileNameLength - $reservedLength
    if ($maxPrefixLength -gt 0) {
      if ($prefixPart.Length -gt $maxPrefixLength) {
        $prefixPart = $prefixPart.Substring(0, $maxPrefixLength)
      }
      $prefixPart = $prefixPart.TrimEnd([char[]]@('.', ' ', '-'))
      if (-not [string]::IsNullOrWhiteSpace($prefixPart)) {
        return "$prefixPart$ellipsis$suffixPart$extension"
      }
    }

    return $FallbackName
  }

  return $fileName
}

function Get-ToolOutputSummary {
  param(
    [object[]]$Output,
    [string]$DefaultMessage = "See _BatchPlotLog.txt for details."
  )

  $lines = @(
    $Output |
      ForEach-Object { [string]$_ } |
      Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
  )
  if ($lines.Count -eq 0) { return $DefaultMessage }

  $summary = $lines |
    Where-Object { $_ -match '(?i)(critical error|error|failed|cannot open|traceback|no pages)' } |
    Select-Object -First 1
  if ([string]::IsNullOrWhiteSpace($summary)) {
    $summary = $lines | Select-Object -Last 1
  }
  if ($summary.Length -gt 260) {
    $summary = "$($summary.Substring(0, 257).TrimEnd())..."
  }
  return $summary
}

function Resolve-CombinedPdfName {
  param(
    [string]$DwgPath,
    [string]$OutputDirectory = "",
    [int]$MaxFullPathLength = 240
  )

  $fallbackName = "combined.pdf"
  if ([string]::IsNullOrWhiteSpace($DwgPath)) { return $fallbackName }

  try {
    $dwgItem = Get-Item -LiteralPath $DwgPath -ErrorAction Stop
  }
  catch {
    return $fallbackName
  }

  $parentDir = $dwgItem.Directory
  if ($null -eq $parentDir -or $null -eq $parentDir.Parent) {
    return $fallbackName
  }

  $projectDir = $parentDir.Parent
  $projectName = ($projectDir.Name -replace '^\s*\d{5,}\s*[-_.]*\s*', '').Trim()
  if ([string]::IsNullOrWhiteSpace($projectName)) {
    $projectName = $projectDir.Name
  }

  $rawName = "$projectName - $($parentDir.Name)"
  $maxFileNameLength = Get-MaxPdfFileNameLengthForDirectory -OutputDirectory $OutputDirectory -MaxFullPathLength $MaxFullPathLength
  return Convert-ToSafePdfFileName -BaseName $rawName -FallbackName $fallbackName -MaxFileNameLength $maxFileNameLength -PreserveSuffix $parentDir.Name
}

# --- SCRIPT CONFIGURATION ---
# Logic to find AutoCAD Core Console
if ($AcadCore -and (Test-Path -Path $AcadCore)) {
  $acadCore = $AcadCore
  Write-Host "PROGRESS: Using specified AutoCAD Core Console: $AcadCore"
}
else {
  $acadCore = $null
  $years = 2025, 2024, 2023, 2022, 2021, 2020

  foreach ($year in $years) {
    $possiblePath = "C:\Program Files\Autodesk\AutoCAD $year\accoreconsole.exe"
    if (Test-Path -Path $possiblePath) {
      $acadCore = $possiblePath
      Write-Host "PROGRESS: Found AutoCAD $year Core Console."
      break # Stop searching once the latest version is found
    }
  }
}

# Name of the Python executable (can be python, python3, or a full path)
$pythonExecutable = "python"
$MaxCombinedPdfFullPathLength = 240

# --- DEFINE AVAILABLE PAPER SIZES ---
$paperSizes = @(
  "ARCH full bleed E (36.00 x 48.00 Inches)",
  "ARCH full bleed E1 (30.00 x 42.00 Inches)",
  "ARCH full bleed D (24.00 x 36.00 Inches)",
  "ANSI full bleed D (22.00 x 34.00 Inches)"
)

# --- SCRIPT AND PYTHON VALIDATION ---
# Get the directory where this script is located
$scriptRoot = $PSScriptRoot
$pythonScriptPath = Join-Path $scriptRoot "merge_pdfs.py"
$detectSizeScriptPath = Join-Path $scriptRoot "detect_pdf_size.py"
$shrinkScriptPath = Join-Path $scriptRoot "shrink_pdf.py"
$stripPdfLayersScriptPath = Join-Path $scriptRoot "strip_pdf_layers.py"
# Check if the Python script exists
if (-not (Test-Path $pythonScriptPath)) {
  Write-Host "PROGRESS: ERROR: 'merge_pdfs.py' not found."
  exit 1
}
if ($StripPdfLayers -and -not (Test-Path $stripPdfLayersScriptPath)) {
  Write-Host "PROGRESS: ERROR: 'strip_pdf_layers.py' not found."
  exit 1
}
# Check if Python is available in the system's PATH
$pythonCheck = Get-Command $pythonExecutable -ErrorAction SilentlyContinue
if (-not $pythonCheck) {
  Write-Host "PROGRESS: ERROR: Python executable ('$pythonExecutable') not found in PATH."
  exit 1
}
# Relaunch in STA mode for the file picker dialog to work correctly
if ([System.Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
  $ps = (Get-Process -Id $PID).Path
  $argsList = @("-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
  if ($AcadCore) { $argsList += @("-AcadCore", $AcadCore) }
  if ($PSBoundParameters.ContainsKey('AutoDetectPaperSize')) {
    $argsList += @("-AutoDetectPaperSize", $AutoDetectPaperSize)
  }
  if ($PSBoundParameters.ContainsKey('AutoAcceptDetectedPaperSize')) {
    $argsList += @("-AutoAcceptDetectedPaperSize", $AutoAcceptDetectedPaperSize)
  }
  if ($PSBoundParameters.ContainsKey('ShrinkPercent')) {
    $argsList += @("-ShrinkPercent", $ShrinkPercent)
  }
  if ($PSBoundParameters.ContainsKey('StripPdfLayers')) {
    $argsList += @("-StripPdfLayers", $StripPdfLayers)
  }
  if ($PSBoundParameters.ContainsKey('RefreshExcelOleLinks')) {
    $argsList += @("-RefreshExcelOleLinks", $RefreshExcelOleLinks)
  }
  if ($PSBoundParameters.ContainsKey('FilesListPath') -and -not [string]::IsNullOrWhiteSpace($FilesListPath)) {
    $argsList += @("-FilesListPath", $FilesListPath)
  }
  if ($PSBoundParameters.ContainsKey('DefaultDirectory') -and -not [string]::IsNullOrWhiteSpace($DefaultDirectory)) {
    $argsList += @("-DefaultDirectory", $DefaultDirectory)
  }
  $child = Start-Process -FilePath $ps -ArgumentList $argsList -Wait -PassThru
  exit $child.ExitCode
}
# Validate that accoreconsole.exe exists
if ([string]::IsNullOrEmpty($acadCore) -or -not (Test-Path $acadCore)) {
  Write-Host "PROGRESS: ERROR: AutoCAD Core Console not found for versions 2020-2025."
  Write-Host "Please ensure AutoCAD is installed in the default 'C:\Program Files\Autodesk' directory."
  exit 1
}

$arcAlignedTextSupportCandidates = [System.Collections.Generic.List[string]]::new()
$acadInstallDir = Split-Path -Path $acadCore -Parent
$fullAcadExe = if ([string]::IsNullOrWhiteSpace($acadInstallDir)) {
  ""
} else {
  Join-Path $acadInstallDir "acad.exe"
}
if (-not [string]::IsNullOrWhiteSpace($acadInstallDir)) {
  $candidateFromExpress = Join-Path $acadInstallDir "Express\ctextapp.arx"
  $candidateFromRoot = Join-Path $acadInstallDir "ctextapp.arx"
  foreach ($candidate in @($candidateFromExpress, $candidateFromRoot)) {
    if (-not [string]::IsNullOrWhiteSpace($candidate)) {
      [void]$arcAlignedTextSupportCandidates.Add($candidate)
    }
  }
}
[void]$arcAlignedTextSupportCandidates.Add("ctextapp.arx")
$arcAlignedTextSupportCandidates = @(
  $arcAlignedTextSupportCandidates |
    Where-Object { $_ -and $_.Trim() } |
    Select-Object -Unique
)
$arcAlignedTextSupportCandidatesForLisp = @(
  $arcAlignedTextSupportCandidates | ForEach-Object { Convert-ToLispPath $_ }
)
$lispArcAlignedTextSupportCandidates = Convert-ToLispQuotedList $arcAlignedTextSupportCandidatesForLisp
$arcAlignedTextFailureMarker = "ACIES_ERROR: ARCALIGNEDTEXT_NOT_SUPPORTED"
$arcCheckPresentMarker = "ACIES_ARC_CHECK:PRESENT"
$arcCheckAbsentMarker = "ACIES_ARC_CHECK:ABSENT"
$arcModuleLoadSuccessMarker = "ACIES_ARC_MODULE_LOAD:SUCCESS"
$arcModuleLoadFailedMarker = "ACIES_ARC_MODULE_LOAD:FAILED"
$arcModuleLoadSkippedMarker = "ACIES_ARC_MODULE_LOAD:SKIPPED"
$plotDecisionContinueMarker = "ACIES_PLOT_DECISION:CONTINUE"
$plotDecisionSkipMarker = "ACIES_PLOT_DECISION:SKIP"
$plotDecisionRefreshOleMarker = "ACIES_PLOT_DECISION:REFRESH_OLE"
$preflightErrorMarker = "ACIES_PREFLIGHT_ERROR"
$oleCheckPresentMarker = "ACIES_OLE_CHECK:PRESENT"
$oleCheckAbsentMarker = "ACIES_OLE_CHECK:ABSENT"
$oleCheckErrorMarker = "ACIES_OLE_CHECK:ERROR"
$oleRefreshRequiredMarker = "ACIES_OLE_REFRESH:REQUIRED"
Write-Host "PROGRESS: ARCALIGNEDTEXT module candidates: $($arcAlignedTextSupportCandidates -join '; ')"

function Invoke-FullAutoCadOleRefresh {
  param(
    [string]$AcadExe,
    [string]$DwgPath,
    [string]$LogFile,
    [int]$TimeoutSeconds = 180,
    [int]$RefreshWaitSeconds = 15
  )

  if ([string]::IsNullOrWhiteSpace($AcadExe) -or -not (Test-Path -LiteralPath $AcadExe -PathType Leaf)) {
    return [pscustomobject]@{
      Status = "unavailable"
      Message = "Full AutoCAD executable was not found beside the selected Core Console."
    }
  }

  $dwgItem = Get-Item -LiteralPath $DwgPath
  if ($dwgItem.IsReadOnly) {
    return [pscustomobject]@{
      Status = "read_only"
      Message = "The drawing is read-only and cannot be saved after refreshing linked Excel content."
    }
  }

  $refreshId = [guid]::NewGuid().ToString("N")
  $refreshScript = Join-Path $env:TEMP "acies_refresh_ole_$refreshId.scr"
  $refreshCompleteMarker = Join-Path $env:TEMP "acies_refresh_ole_$refreshId.complete"
  $refreshCompleteMarkerForLisp = Convert-ToLispPath $refreshCompleteMarker
  $refreshWaitMilliseconds = [Math]::Max(1, [Math]::Min(30, $RefreshWaitSeconds)) * 1000
  $scriptContent = @"
(setvar "FILEDIA" 0)
(setvar "CMDDIA" 0)
(command "_.DELAY" $refreshWaitMilliseconds)
(command "_.REGENALL")
(command "_.DELAY" 2000)
(command "_.QSAVE")
(progn (setq aciesOleRefreshMarker (open "$refreshCompleteMarkerForLisp" "w")) (if aciesOleRefreshMarker (progn (write-line "ACIES_OLE_REFRESH:COMPLETE" aciesOleRefreshMarker) (close aciesOleRefreshMarker))))
(command "_.QUIT")
"@

  try {
    Set-Content -Encoding ASCII -LiteralPath $refreshScript -Value $scriptContent
    $argumentLine = ('"{0}" /nologo /nohardware /nossm /b "{1}"' -f $DwgPath, $refreshScript)
    "OLE_REFRESH_COMMAND: $AcadExe $argumentLine" | Out-File $LogFile -Append
    "OLE_REFRESH_WAIT_SECONDS: $RefreshWaitSeconds" | Out-File $LogFile -Append

    $process = Start-Process -FilePath $AcadExe `
      -ArgumentList $argumentLine `
      -PassThru `
      -WorkingDirectory (Split-Path -Path $AcadExe -Parent) `
      -WindowStyle Hidden

    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
      try { $process.Kill() } catch {}
      try { $null = $process.WaitForExit() } catch {}
      return [pscustomobject]@{
        Status = "timeout"
        Message = "Full AutoCAD did not finish the OLE refresh within $TimeoutSeconds seconds."
      }
    }

    if ($process.ExitCode -ne 0) {
      return [pscustomobject]@{
        Status = "failed"
        Message = "Full AutoCAD exited with code $($process.ExitCode) while refreshing linked Excel content."
      }
    }

    if (-not (Test-Path -LiteralPath $refreshCompleteMarker -PathType Leaf)) {
      return [pscustomobject]@{
        Status = "incomplete"
        Message = "Full AutoCAD exited without confirming that the drawing was opened, refreshed, and saved."
      }
    }

    return [pscustomobject]@{
      Status = "success"
      Message = "Linked Excel OLE content was given time to refresh in full AutoCAD and the drawing was saved."
    }
  }
  catch {
    return [pscustomobject]@{
      Status = "failed"
      Message = "Could not refresh linked Excel OLE content: $($_.Exception.Message)"
    }
  }
  finally {
    foreach ($tempPath in @($refreshScript, $refreshCompleteMarker)) {
      if (Test-Path -LiteralPath $tempPath -PathType Leaf) {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
      }
    }
  }
}

Ensure-WinFormsAssemblies

# --- Resolve DWG files: prefer preselected list, otherwise prompt ---
$files = @()
$filesListWasProvided = $PSBoundParameters.ContainsKey('FilesListPath')
$hasFilesListPath = $filesListWasProvided -and -not [string]::IsNullOrWhiteSpace($FilesListPath)
Write-Host "PROGRESS: TRACE files_list_param_bound=$([int]$filesListWasProvided) path=$FilesListPath"
if ($filesListWasProvided) {
  if ($hasFilesListPath) {
    Write-Host "PROGRESS: Received auto-selected files list: $FilesListPath"
    if (Test-Path $FilesListPath) {
      Write-Host "PROGRESS: TRACE files_list_path_exists=1"
      $files = @(
        Get-Content -Path $FilesListPath -Encoding UTF8 |
          Where-Object { $_ -and $_.Trim() -and (Test-Path $_.Trim()) } |
          ForEach-Object { $_.Trim() }
      )
      Write-Host "PROGRESS: TRACE files_list_valid_count=$($files.Count)"
      if ($files.Count -gt 0) {
        Write-Host "PROGRESS: Using $($files.Count) DWG file(s) from auto-selected project folder."
      }
      else {
        Write-Host "PROGRESS: Provided files list was empty. Opening file picker..."
      }
    }
    else {
      Write-Host "PROGRESS: TRACE files_list_path_exists=0"
      Write-Host "PROGRESS: Provided files list path was not found. Opening file picker..."
    }
  }
  else {
    Write-Host "PROGRESS: TRACE files_list_param_empty=1"
    Write-Host "PROGRESS: Files list parameter was provided without a path. Opening file picker..."
  }
}

if ($files -and $files.Count -gt 0) {
  Write-Host "PROGRESS: TRACE branch=auto_selected_files count=$($files.Count)"
}

if (-not $files -or $files.Count -eq 0) {
  Write-Host "PROGRESS: TRACE branch=manual_picker"
  Write-Host "PROGRESS: Waiting for user input..."
  Write-Host "PROGRESS: File selection dialog should be visible on the primary display."
  [System.Windows.Forms.Application]::EnableVisualStyles()

  $selectedDwgFiles = Show-DwgFileSelectionPrompt
  if (-not $selectedDwgFiles -or $selectedDwgFiles.Count -eq 0) {
    Write-Host "PROGRESS: ERROR: No files selected."; exit
  }
  $files = $selectedDwgFiles
}

# Normalize to a string array so single-file runs still behave like multi-file runs.
$files = @($files)
$inputFolder = ""
if ($files.Count -gt 0) {
  $inputFolder = Split-Path -Path ([string]$files[0]) -Parent
}
if (-not [string]::IsNullOrWhiteSpace($inputFolder)) {
  Write-Host "PROGRESS: INPUT_FOLDER: $inputFolder"
}

# --- Detect paper size from existing project PDFs ---
$detectedPaperSize = ""
$detectionStatus = "not_checked"
if ($AutoDetectPaperSize) {
  if (Test-Path $detectSizeScriptPath) {
    Write-Host "PROGRESS: Detecting paper size from existing PDFs..."
    try {
      # PowerShell passes a string argument with spaces intact. Adding literal
      # quote characters here prevents the detector from resolving the project.
      $detectOutput = & $pythonExecutable $detectSizeScriptPath ([string]$files[0]) 2>&1

      # Check if there was an error (stderr output will be error records)
      $errorOutput = $detectOutput | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] }
      $stdOutput = $detectOutput | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] }

      if ($stdOutput) {
        $detectedPaperSize = ($stdOutput | Out-String).Trim()
      }

      if ($detectedPaperSize -and ($paperSizes -contains $detectedPaperSize)) {
        Write-Host "PROGRESS: Detected paper size: $detectedPaperSize"
        $detectionStatus = "detected"
      } else {
        if ($detectedPaperSize) {
          Write-Host "PROGRESS: Detected an unsupported paper size: $detectedPaperSize"
          $detectedPaperSize = ""
        }
        if ($errorOutput) {
          Write-Host "PROGRESS: Detection error: $($errorOutput | Out-String)"
        }
        Write-Host "PROGRESS: No matching paper size found in project PDFs."
        $detectionStatus = "no_match"
      }
    }
    catch {
      Write-Host "PROGRESS: Could not detect paper size: $_"
      $detectionStatus = "error"
      $detectedPaperSize = ""
    }
  } else {
    Write-Host "PROGRESS: Detection script not found at: $detectSizeScriptPath"
    $detectionStatus = "script_missing"
  }
}
else {
  Write-Host "PROGRESS: Auto-detect disabled. Please enter paper size manually."
  $detectionStatus = "disabled"
}

# --- Automatically accept a valid detected size or ask the user for one ---
$selectedPaperSize = ""
if ($AutoAcceptDetectedPaperSize -and $detectionStatus -eq "detected" -and $detectedPaperSize) {
  $selectedPaperSize = $detectedPaperSize
  Write-Host "PROGRESS: Automatically using detected paper size: $selectedPaperSize"
  Write-Host "PROGRESS: TRACE branch=paper_size_auto_accepted"
}
else {
if ($AutoAcceptDetectedPaperSize) {
  Write-Host "PROGRESS: Automatic paper-size selection unavailable ($detectionStatus). Please enter or select a paper size."
  Write-Host "PROGRESS: INPUT_REQUIRED: PAPER_SIZE"
}

# --- Let the user select/confirm a paper size ---
$form = New-Object System.Windows.Forms.Form
$form.Text = "Select Paper Size"
$form.Size = New-Object System.Drawing.Size(450, 200)
$form.StartPosition = "Manual"
$form.TopMost = $true
$form.ShowInTaskbar = $true
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
Move-FormToPrimaryScreen $form

# Status label to show detection result
$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Location = New-Object System.Drawing.Point(10, 15)
$statusLabel.Size = New-Object System.Drawing.Size(420, 20)
$statusLabel.Font = New-Object System.Drawing.Font($statusLabel.Font.FontFamily, 9, [System.Drawing.FontStyle]::Bold)
switch ($detectionStatus) {
  "detected" {
    $statusLabel.Text = "Paper size detected from existing project PDFs"
    $statusLabel.ForeColor = [System.Drawing.Color]::Green
  }
  "no_match" {
    $statusLabel.Text = "No matching PDFs found in project folder"
    $statusLabel.ForeColor = [System.Drawing.Color]::DarkOrange
  }
  "disabled" {
    $statusLabel.Text = "Auto-detect disabled"
    $statusLabel.ForeColor = [System.Drawing.Color]::Gray
  }
  default {
    $statusLabel.Text = "Auto-detection not available"
    $statusLabel.ForeColor = [System.Drawing.Color]::Gray
  }
}
$form.Controls.Add($statusLabel)

$label = New-Object System.Windows.Forms.Label
$label.Location = New-Object System.Drawing.Point(10, 45)
$label.Size = New-Object System.Drawing.Size(420, 20)
if ($detectedPaperSize) {
  $label.Text = "Confirm the detected size or select a different one:"
} elseif ($AutoDetectPaperSize) {
  $label.Text = "Please select a paper size for plotting:"
} else {
  $label.Text = "Please enter or select a paper size for plotting:"
}
$form.Controls.Add($label)

$comboBox = New-Object System.Windows.Forms.ComboBox
$comboBox.Location = New-Object System.Drawing.Point(10, 70)
$comboBox.Size = New-Object System.Drawing.Size(410, 20)
if ($AutoDetectPaperSize) {
  $comboBox.DropDownStyle = "DropDownList"
}
else {
  $comboBox.DropDownStyle = "DropDown"
}

# Add paper sizes with checkmark for detected size
$selectedIndex = 0
$index = 0
foreach ($size in $paperSizes) {
  if ($detectedPaperSize -and $size -eq $detectedPaperSize) {
    [void] $comboBox.Items.Add("$size  [Detected]")
    $selectedIndex = $index
  } else {
    [void] $comboBox.Items.Add($size)
  }
  $index++
}
if ($AutoDetectPaperSize -and $comboBox.Items.Count -gt 0) {
  $comboBox.SelectedIndex = $selectedIndex
}
$form.Controls.Add($comboBox)

$okButton = New-Object System.Windows.Forms.Button
$okButton.Location = New-Object System.Drawing.Point(175, 110)
$okButton.Size = New-Object System.Drawing.Size(75, 23)
$okButton.Text = "OK"
$okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.AcceptButton = $okButton
$form.Controls.Add($okButton)

$form.add_Shown({
    $form.TopMost = $true
    $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
    Move-FormToPrimaryScreen $form
    $form.Activate()
    $form.BringToFront()
    $comboBox.Focus()
  })

$form.add_Resize({
    if ($form.WindowState -eq [System.Windows.Forms.FormWindowState]::Minimized) {
      $form.WindowState = [System.Windows.Forms.FormWindowState]::Normal
      Move-FormToPrimaryScreen $form
      $form.Activate()
      $form.BringToFront()
    }
  })

Write-Host "PROGRESS: Waiting for paper size confirmation..."
Write-Host "PROGRESS: Paper size dialog should be visible on the primary display."
Write-Host "PROGRESS: TRACE branch=paper_size_dialog"
$result = $form.ShowDialog()

if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
  Write-Host "PROGRESS: ERROR: Operation cancelled by user."; exit
}

# Remove the " [Detected]" suffix if present to get the actual paper size
$selectedPaperSize = ($comboBox.Text -replace '\s+\[Detected\]$', '').Trim()
if ([string]::IsNullOrWhiteSpace($selectedPaperSize)) {
  Write-Host "PROGRESS: ERROR: No paper size selected."
  exit 1
}
}

# --- BATCH PROCESSING SETUP ---
Write-Host "PROGRESS: Preparing to plot $($files.Count) file(s)..."
$basePlotDir = Join-Path -Path ([Environment]::GetFolderPath("MyDocuments")) -ChildPath "AutoCAD Plots"
$timestamp = Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'
$firstDwgItem = Get-Item -LiteralPath ([string]$files[0])
$firstFileParentDirName = $firstDwgItem.Directory.Parent.Name
$batchOutputDir = Join-Path -Path (Join-Path -Path $basePlotDir -ChildPath $firstFileParentDirName) -ChildPath $timestamp
New-Item -ItemType Directory -Force -Path $batchOutputDir | Out-Null
$combinedPdfName = Resolve-CombinedPdfName -DwgPath ([string]$files[0]) -OutputDirectory $batchOutputDir -MaxFullPathLength $MaxCombinedPdfFullPathLength

# --- SINGLE LOG FILE SETUP ---
$logFile = Join-Path $batchOutputDir "_BatchPlotLog.txt"
"===== Batch Plot Started: $(Get-Date -f 'yyyy-MM-dd HH:mm:ss') =====" | Out-File $logFile
"Selected Paper Size: $selectedPaperSize" | Out-File $logFile -Append
"AutoCAD Core Used: $acadCore" | Out-File $logFile -Append
"ARCALIGNEDTEXT module candidates: $($arcAlignedTextSupportCandidates -join '; ')" | Out-File $logFile -Append
"Strip PDF Layers: $StripPdfLayers" | Out-File $logFile -Append
"Refresh Excel OLE Links: $RefreshExcelOleLinks" | Out-File $logFile -Append
"Full AutoCAD Executable: $fullAcadExe" | Out-File $logFile -Append
"Output Folder: $batchOutputDir" | Out-File $logFile -Append
"Combined PDF Name: $combinedPdfName" | Out-File $logFile -Append
"Processing $($files.Count) files..." | Out-File $logFile -Append

# Initialize lists to track progress and generated files
$allGeneratedPdfs = [System.Collections.ArrayList]::new()
$failed = @()
$oleRefreshFailures = @()
$arcAlignedTextSupportFailures = @()
$noPdfOutputFailures = @()
$pdfMergeFailed = $false
$pdfLayerCleanupFailed = $false
$i = 0

function Invoke-CorePlotAttempt {
  param(
    [string]$DwgPath,
    [string]$DwgNameWithoutExt,
    [string]$OutputDirectory,
    [string]$PaperSize,
    [string]$LogFile,
    [bool]$OleRefreshAlreadyAttempted
  )

  $attemptId = [guid]::NewGuid().ToString("N")
  $lispFile = Join-Path $env:TEMP "plot_layouts_$attemptId.lsp"
  $scriptFile = Join-Path $env:TEMP "run_plot_$attemptId.scr"
  $lispOutputDir = $OutputDirectory -replace '\\', '\\'
  $oleRefreshEnabledLiteral = if ($RefreshExcelOleLinks) { "T" } else { "nil" }
  $oleRefreshAttemptedLiteral = if ($OleRefreshAlreadyAttempted) { "T" } else { "nil" }

  $lispContent = @"
(setq *acies-refresh-excel-ole-links* $oleRefreshEnabledLiteral)
(setq *acies-ole-refresh-attempted* $oleRefreshAttemptedLiteral)

(defun InspectLinkedOLEs (/ selection count)
  ;; DXF group 71 identifies the OLE item type: 1=linked, 2=embedded,
  ;; 3=static. ssget avoids ActiveX, which is not dependable in Core Console.
  (setq selection (ssget "_X" '((0 . "OLE2FRAME") (71 . 1))))
  (setq count (if selection (sslength selection) 0))
  (if (> count 0)
    (princ (strcat "\n${oleCheckPresentMarker}:" (itoa count)))
    (princ "\n$oleCheckAbsentMarker")
  )
  count
)

(defun SafeInspectLinkedOLEs (/ result)
  (setq result (vl-catch-all-apply 'InspectLinkedOLEs '()))
  (if (vl-catch-all-error-p result)
    (progn
      (princ (strcat "\n${oleCheckErrorMarker}: " (vl-catch-all-error-message result)))
      -1
    )
    result
  )
)

(defun AciesLog (msg)
  (princ (strcat "\n" msg))
)

(defun AciesSafeArxLoad (module / res msg)
  (if (and module (> (strlen module) 0))
    (progn
      (setq res (vl-catch-all-apply 'arxload (list module)))
      (if (vl-catch-all-error-p res)
        (progn
          (setq msg (strcase (vl-catch-all-error-message res)))
          (or (wcmatch msg "*ALREADY*LOADED*")
              (wcmatch msg "*DUPLICATE*LOAD*"))
        )
        T
      )
    )
    nil
  )
)

(defun EnsureArcAlignedTextSupport (/ candidates candidate resolved loaded)
  (setq loaded nil)
  (setq candidates (list $lispArcAlignedTextSupportCandidates))
  (foreach candidate candidates
    (if (not loaded)
      (progn
        (setq resolved (findfile candidate))
        (if (not resolved)
          (setq resolved candidate)
        )
        (if (AciesSafeArxLoad resolved)
          (setq loaded T)
        )
      )
    )
  )
  loaded
)

(defun SafeRegenAll (/ result)
  (setq result (vl-catch-all-apply 'command (list "._REGENALL")))
  (if (vl-catch-all-error-p result)
    (AciesLog (strcat "REGENALL skipped: " (vl-catch-all-error-message result)))
  )
)

(defun EnsurePublishPreflight (/ hasArcAlignedText arcSupportLoaded arcSelectResult)
  (setvar "BACKGROUNDPLOT" 0)
  (setvar "FILEDIA" 0)
  (setvar "DEMANDLOAD" 3)
  (setvar "PROXYSHOW" 1)
  (setq hasArcAlignedText nil)
  (setq arcSelectResult (vl-catch-all-apply 'ssget (list "_X" (list (cons 0 "ARCALIGNEDTEXT")))))
  (if (vl-catch-all-error-p arcSelectResult)
    (progn
      (AciesLog (strcat "${preflightErrorMarker}: " (vl-catch-all-error-message arcSelectResult)))
      (AciesLog "$plotDecisionSkipMarker")
      nil
    )
    (progn
      (setq hasArcAlignedText (and arcSelectResult (> (sslength arcSelectResult) 0)))
      (if hasArcAlignedText
        (progn
          (AciesLog "$arcCheckPresentMarker")
          (AciesLog "Loading ARCALIGNEDTEXT support module (ctextapp.arx)...")
          (setq arcSupportLoaded (EnsureArcAlignedTextSupport))
          (SafeRegenAll)
          (if arcSupportLoaded
            (progn
              (AciesLog "$arcModuleLoadSuccessMarker")
              (AciesLog "$plotDecisionContinueMarker")
              T
            )
            (progn
              (AciesLog "$arcModuleLoadFailedMarker")
              (AciesLog "$arcAlignedTextFailureMarker")
              (AciesLog "$plotDecisionSkipMarker")
              nil
            )
          )
        )
        (progn
          (AciesLog "$arcCheckAbsentMarker")
          (AciesLog "$arcModuleLoadSkippedMarker")
          (AciesLog "$plotDecisionContinueMarker")
          T
        )
      )
    )
  )
)

(defun PlotLayoutsAfterPreflight (/ main-dict layout-dict item layout-name pdfName preflightResult)
  (setq preflightResult (vl-catch-all-apply 'EnsurePublishPreflight '()))
  (if (vl-catch-all-error-p preflightResult)
    (progn
      (AciesLog (strcat "${preflightErrorMarker}: " (vl-catch-all-error-message preflightResult)))
      (AciesLog "$plotDecisionSkipMarker")
      (command "QUIT" "N")
    )
    (if preflightResult
      (progn
        (setq main-dict (namedobjdict))
        (setq layout-dict (dictsearch main-dict "ACAD_LAYOUT"))
        (foreach item layout-dict
          (if (= (car item) 3)
            (progn
              (setq layout-name (cdr item))
              (if (/= (strcase layout-name) "MODEL")
                (progn
                  (setvar "CTAB" layout-name)
                  (setq pdfName (strcat "$lispOutputDir\\" "$DwgNameWithoutExt" "-" layout-name ".pdf"))
                  (command "-PLOT" "Y" "" "DWG to PDF.pc3" "$PaperSize" "I" "L" "N" "L" "1:1" "0.00,0.00" "Y" "510-monochrome.ctb" "Y" "N" "N" "N" pdfName "N" "Y")
                )
              )
            )
          )
        )
        (command "QUIT" "N")
      )
      (progn
        (AciesLog "Skipping plot because ARCALIGNEDTEXT support is unavailable in headless mode.")
        (command "QUIT" "N")
      )
    )
  )
)

(defun c:PlotAllLayouts (/ linkedOleCount)
  (setq linkedOleCount (SafeInspectLinkedOLEs))
  (cond
    ((< linkedOleCount 0)
      (AciesLog "$plotDecisionSkipMarker")
      (command "QUIT" "N")
    )
    ((and *acies-refresh-excel-ole-links*
          (not *acies-ole-refresh-attempted*)
          (> linkedOleCount 0))
      (AciesLog "$oleRefreshRequiredMarker")
      (AciesLog "$plotDecisionRefreshOleMarker")
      (command "QUIT" "N")
    )
    (T (PlotLayoutsAfterPreflight))
  )
  (princ)
)
"@

  try {
    Set-Content -Encoding ASCII -LiteralPath $lispFile -Value $lispContent
    $lispPathForScript = $lispFile -replace '\\', '/'
    $scriptContent = @"
(load "$lispPathForScript")
PlotAllLayouts
"@
    Set-Content -Encoding ASCII -LiteralPath $scriptFile -Value $scriptContent

    $plotOutput = & $acadCore /i "$DwgPath" /s "$scriptFile" 2>&1 | Tee-Object -FilePath $LogFile -Append
    return [pscustomobject]@{
      Output = @($plotOutput)
      ExitCode = $LASTEXITCODE
    }
  }
  finally {
    foreach ($tempPath in @($lispFile, $scriptFile)) {
      if (Test-Path -LiteralPath $tempPath -PathType Leaf) {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
      }
    }
  }
}

# --- Main Processing Loop (Plotting ONLY) ---
foreach ($dwgPath in $files) {
  $i++
  $dwgItem = Get-Item $dwgPath
  $dwgNameWithoutExt = $dwgItem.BaseName
  Write-Host "PROGRESS: Plotting $i of $($files.Count): $($dwgItem.Name)"

  "===== $(Get-Date -f 'yyyy-MM-dd HH:mm:ss') Start Plotting: $($dwgItem.Name) =====" | Out-File $logFile -Append

  $existingPerDwgPdfs = @(Get-ChildItem -Path $batchOutputDir -Filter "$($dwgNameWithoutExt)-*.pdf" -ErrorAction SilentlyContinue)
  $existingPerDwgPdfSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($existingPdf in $existingPerDwgPdfs) {
    [void]$existingPerDwgPdfSet.Add($existingPdf.FullName)
  }

  $plotAttempt = Invoke-CorePlotAttempt `
    -DwgPath $dwgPath `
    -DwgNameWithoutExt $dwgNameWithoutExt `
    -OutputDirectory $batchOutputDir `
    -PaperSize $selectedPaperSize `
    -LogFile $logFile `
    -OleRefreshAlreadyAttempted $false
  $plotOutput = @($plotAttempt.Output)
  $code = $plotAttempt.ExitCode

  $initialPlotOutputText = ($plotOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine
  $initialPlotOutputNormalized = $initialPlotOutputText -replace ([char]0), ''
  $oleRefreshRequired = $RefreshExcelOleLinks -and (
    $initialPlotOutputNormalized -match [regex]::Escape($oleRefreshRequiredMarker)
  )

  if ($oleRefreshRequired) {
    Write-Host "PROGRESS: Linked Excel OLE content detected in $($dwgItem.Name)."
    Write-Host "PROGRESS: Refreshing linked Excel content in $($dwgItem.Name) and saving the drawing..."
    "OLE_REFRESH: Required for $dwgPath" | Out-File $logFile -Append
    $oleRefreshResult = Invoke-FullAutoCadOleRefresh `
      -AcadExe $fullAcadExe `
      -DwgPath $dwgPath `
      -LogFile $logFile `
      -TimeoutSeconds 180

    "OLE_REFRESH_RESULT: $($oleRefreshResult.Status) - $($oleRefreshResult.Message)" | Out-File $logFile -Append
    if ($oleRefreshResult.Status -eq "success") {
      Write-Host "PROGRESS: Refreshed linked Excel content and saved $($dwgItem.Name)."
    }
    else {
      Write-Host "PROGRESS: ERROR: $($dwgItem.Name) - $($oleRefreshResult.Message) Plot skipped to prevent stale OLE content."
      "Plot skipped because linked Excel OLE refresh did not complete." | Out-File $logFile -Append
      if (-not ($oleRefreshFailures -contains $dwgPath)) {
        $oleRefreshFailures += $dwgPath
      }
      if (-not ($failed -contains $dwgPath)) {
        $failed += $dwgPath
      }
      "===== $(Get-Date -f 'yyyy-MM-dd HH:mm:ss') Done: $($dwgItem.Name) =====" | Out-File $logFile -Append
      continue
    }

    $plotAttempt = Invoke-CorePlotAttempt `
      -DwgPath $dwgPath `
      -DwgNameWithoutExt $dwgNameWithoutExt `
      -OutputDirectory $batchOutputDir `
      -PaperSize $selectedPaperSize `
      -LogFile $logFile `
      -OleRefreshAlreadyAttempted $true
    $plotOutput = @($plotAttempt.Output)
    $code = $plotAttempt.ExitCode
  }

  $plotOutputText = ($plotOutput | ForEach-Object { "$_" }) -join [Environment]::NewLine
  $plotOutputTextNormalized = $plotOutputText -replace ([char]0), ''
  $normalizedOutputLines = @(
    $plotOutput | ForEach-Object { ("$_" -replace ([char]0), '') }
  )
  $arcCheckPresent = $plotOutputTextNormalized -match [regex]::Escape($arcCheckPresentMarker)
  $arcCheckAbsent = $plotOutputTextNormalized -match [regex]::Escape($arcCheckAbsentMarker)
  $arcModuleLoadSuccess = $plotOutputTextNormalized -match [regex]::Escape($arcModuleLoadSuccessMarker)
  $arcModuleLoadFailed = $plotOutputTextNormalized -match [regex]::Escape($arcModuleLoadFailedMarker)
  $arcModuleLoadSkipped = $plotOutputTextNormalized -match [regex]::Escape($arcModuleLoadSkippedMarker)
  $plotDecisionContinue = $plotOutputTextNormalized -match [regex]::Escape($plotDecisionContinueMarker)
  $plotDecisionSkip = $plotOutputTextNormalized -match [regex]::Escape($plotDecisionSkipMarker)
  $oleCheckPresent = $plotOutputTextNormalized -match [regex]::Escape($oleCheckPresentMarker)
  $oleCheckAbsent = $plotOutputTextNormalized -match [regex]::Escape($oleCheckAbsentMarker)
  $oleCheckError = $plotOutputTextNormalized -match [regex]::Escape($oleCheckErrorMarker)
  $missingArcAlignedTextSupport = $plotOutputTextNormalized -match [regex]::Escape($arcAlignedTextFailureMarker)
  $preflightError = $plotOutputTextNormalized -match [regex]::Escape($preflightErrorMarker)
  $preflightErrorLine = @(
    $normalizedOutputLines |
      Where-Object { $_ -like "*$preflightErrorMarker*" } |
      Select-Object -First 1
  )

  $arcCheckStatus = "unknown"
  if ($arcCheckPresent) { $arcCheckStatus = "present" }
  elseif ($arcCheckAbsent) { $arcCheckStatus = "absent" }

  $arcModuleLoadStatus = "unknown"
  if ($arcModuleLoadSuccess) { $arcModuleLoadStatus = "success" }
  elseif ($arcModuleLoadFailed) { $arcModuleLoadStatus = "failed" }
  elseif ($arcModuleLoadSkipped) { $arcModuleLoadStatus = "skipped" }

  $plotDecision = "unknown"
  if ($plotDecisionContinue) { $plotDecision = "continue" }
  elseif ($plotDecisionSkip) { $plotDecision = "skip" }

  $oleCheckStatus = "unknown"
  if ($oleCheckPresent) { $oleCheckStatus = "present" }
  elseif ($oleCheckAbsent) { $oleCheckStatus = "absent" }
  elseif ($oleCheckError) { $oleCheckStatus = "error" }

  if ($oleCheckError) {
    Write-Host "PROGRESS: ERROR: $($dwgItem.Name) - Could not inspect linked Excel OLE objects. Plot skipped to prevent stale OLE content."
  }
  elseif ($oleCheckAbsent) {
    Write-Host "PROGRESS: No linked Excel OLE content detected in $($dwgItem.Name); continuing headless publish."
  }
  elseif ($oleCheckPresent -and -not $RefreshExcelOleLinks) {
    Write-Host "PROGRESS: Linked Excel OLE content detected in $($dwgItem.Name), but automatic refresh is disabled."
  }

  $currentPerDwgPdfs = @(Get-ChildItem -Path $batchOutputDir -Filter "$($dwgNameWithoutExt)-*.pdf" -ErrorAction SilentlyContinue | Sort-Object FullName)
  $newPerDwgPdfs = @($currentPerDwgPdfs | Where-Object { -not $existingPerDwgPdfSet.Contains($_.FullName) })
  $newPerDwgPdfCount = $newPerDwgPdfs.Count

  "ARC_CHECK: $arcCheckStatus" | Out-File $logFile -Append
  "ARC_MODULE_LOAD: $arcModuleLoadStatus" | Out-File $logFile -Append
  "OLE_CHECK: $oleCheckStatus" | Out-File $logFile -Append
  "PLOT_DECISION: $plotDecision" | Out-File $logFile -Append
  "PDF_COUNT_AFTER_DWG: $newPerDwgPdfCount" | Out-File $logFile -Append
  Write-Host "TELEMETRY: $($dwgItem.Name): OLE_CHECK=$oleCheckStatus; ARC_CHECK=$arcCheckStatus; ARC_MODULE_LOAD=$arcModuleLoadStatus; PLOT_DECISION=$plotDecision; PDF_COUNT_AFTER_DWG=$newPerDwgPdfCount"

  $preflightSkipped = ($plotDecision -eq "skip")
  $noPdfOutputFailure = (($plotDecision -eq "continue" -or $plotDecision -eq "unknown") -and $newPerDwgPdfCount -eq 0)

  if ($missingArcAlignedTextSupport -or ($preflightSkipped -and $arcCheckStatus -eq "present" -and $arcModuleLoadStatus -eq "failed")) {
    if (-not ($arcAlignedTextSupportFailures -contains $dwgPath)) {
      $arcAlignedTextSupportFailures += $dwgPath
    }
    Write-Host "PROGRESS: ERROR: $($dwgItem.Name) - ARCALIGNEDTEXT support missing (ctextapp.arx is not loadable by accoreconsole)."
    "ARCALIGNEDTEXT support failure detected in headless plotting output." | Out-File $logFile -Append
    "Hint: Ensure Express Tools is installed and ctextapp.arx is loadable by accoreconsole." | Out-File $logFile -Append
  }
  elseif ($preflightSkipped) {
    Write-Host "PROGRESS: ERROR: $($dwgItem.Name) - Plot skipped by preflight checks."
    "Plot skipped by preflight checks." | Out-File $logFile -Append
  }
  if ($preflightError) {
    $details = if ($preflightErrorLine) { $preflightErrorLine } else { "Preflight reported an unspecified AutoLISP error." }
    Write-Host "PROGRESS: ERROR: $($dwgItem.Name) - $details"
    "Preflight error detail: $details" | Out-File $logFile -Append
  }

  if ($noPdfOutputFailure) {
    if (-not ($noPdfOutputFailures -contains $dwgPath)) {
      $noPdfOutputFailures += $dwgPath
    }
    Write-Host "PROGRESS: ERROR: $($dwgItem.Name) - No PDFs were generated from layouts."
    "No PDFs were generated from layouts for this DWG." | Out-File $logFile -Append
  }

  if ($code -ne 0) {
    Write-Host "PROGRESS: ERROR: $($dwgItem.Name) - accoreconsole exited with code $code."
  }
  "ExitCode: $code" | Out-File $logFile -Append

  if ($code -ne 0 -or $missingArcAlignedTextSupport -or $preflightSkipped -or $preflightError -or $noPdfOutputFailure) {
    if (-not ($failed -contains $dwgPath)) {
      $failed += $dwgPath
    }
  }
  else {
    if ($newPerDwgPdfs.Count -gt 0) {
      $pdfPaths = @($newPerDwgPdfs | ForEach-Object { $_.FullName } | Sort-Object)
      $allGeneratedPdfs.AddRange($pdfPaths)
    }
  }
  "===== $(Get-Date -f 'yyyy-MM-dd HH:mm:ss') Done: $($dwgItem.Name) =====" | Out-File $logFile -Append
}

# --- FINAL MERGE (After the loop) ---
$finalCombinedPdfPath = ""
if ($allGeneratedPdfs.Count -gt 0) {
  Write-Host "PROGRESS: Combining $($allGeneratedPdfs.Count) generated PDFs..."
  $combinedPdfPath = Join-Path $batchOutputDir $combinedPdfName
   
  $pythonArgs = @($combinedPdfPath) + @($allGeneratedPdfs | ForEach-Object { [string]$_ })
    
  $mergeOutput = & $pythonExecutable $pythonScriptPath @pythonArgs 2>&1
   
  if ($LASTEXITCODE -eq 0) {
    "Python script executed successfully." | Out-File $logFile -Append
    $mergeOutput | ForEach-Object { [string]$_ } | Out-File $logFile -Append
    $finalCombinedPdfPath = $combinedPdfPath

    if ($StripPdfLayers) {
      Write-Host "PROGRESS: Removing PDF layers from combined PDF..."
      $stripOutput = & $pythonExecutable $stripPdfLayersScriptPath $combinedPdfPath 2>&1
      if ($LASTEXITCODE -eq 0) {
        "PDF layer cleanup completed." | Out-File $logFile -Append
        "$stripOutput" | Out-File $logFile -Append
      }
      else {
        $pdfLayerCleanupFailed = $true
        $finalCombinedPdfPath = ""
        Write-Host "PROGRESS: ERROR: PDF layer cleanup failed."
        "PDF layer cleanup failed. Output from Python script:" | Out-File $logFile -Append
        "$stripOutput" | Out-File $logFile -Append
      }
    }

    $shrinkPercentInt = [int]$ShrinkPercent
    if ($shrinkPercentInt -lt 5) { $shrinkPercentInt = 5 }
    if ($shrinkPercentInt -gt 100) { $shrinkPercentInt = 100 }
    if (-not $pdfLayerCleanupFailed -and $shrinkPercentInt -lt 100) {
      if (Test-Path $shrinkScriptPath) {
        $combinedPdfBaseName = [System.IO.Path]::GetFileNameWithoutExtension($combinedPdfName)
        $shrunkName = "$combinedPdfBaseName-shrunk-$shrinkPercentInt-percent.tmp.pdf"
        $shrunkPath = Join-Path $batchOutputDir $shrunkName
        if (Test-Path -LiteralPath $shrunkPath -PathType Leaf) {
          Remove-Item -LiteralPath $shrunkPath -Force
        }
        Write-Host "PROGRESS: Shrinking combined PDF to $shrinkPercentInt%..."
        $shrinkOutput = & $pythonExecutable $shrinkScriptPath $combinedPdfPath $shrunkPath $shrinkPercentInt 2>&1
        if ($LASTEXITCODE -eq 0 -and (Test-Path -LiteralPath $shrunkPath -PathType Leaf)) {
          Move-Item -LiteralPath $shrunkPath -Destination $combinedPdfPath -Force
          "Shrunk PDF applied to final output: $combinedPdfName" | Out-File $logFile -Append
          "$shrinkOutput" | Out-File $logFile -Append
          $finalCombinedPdfPath = $combinedPdfPath
        } else {
          Write-Host "PROGRESS: ERROR: PDF shrinking failed."
          "PDF shrinking failed. Output from Python script:" | Out-File $logFile -Append
          "$shrinkOutput" | Out-File $logFile -Append
        }
      } else {
        Write-Host "PROGRESS: ERROR: 'shrink_pdf.py' not found."
        "'shrink_pdf.py' not found; skipped shrinking." | Out-File $logFile -Append
      }
    }
  }
  else {
    $pdfMergeFailed = $true
    $finalCombinedPdfPath = ""
    $mergeErrorSummary = Get-ToolOutputSummary -Output $mergeOutput
    Write-Host "PROGRESS: ERROR: PDF merging failed: $mergeErrorSummary"
    "PDF Merging Failed. Output from Python script:" | Out-File $logFile -Append
    $mergeOutput | ForEach-Object { [string]$_ } | Out-File $logFile -Append
  }
}
else {
  Write-Host "PROGRESS: No PDFs were generated to combine."
  "No PDFs were generated to merge." | Out-File $logFile -Append
}

# --- CLEANUP & NOTIFICATION ---
"===== Batch Plot Finished: $(Get-Date -f 'yyyy-MM-dd HH:mm:ss') =====" | Out-File $logFile -Append
if ($arcAlignedTextSupportFailures.Count) {
  $arcFails = @($arcAlignedTextSupportFailures | Select-Object -Unique)
  $arcFailMsg = "ARCALIGNEDTEXT entities could not be plotted in headless mode because ctextapp.arx could not be loaded: $($arcFails -join ', ')"
  Write-Host "PROGRESS: ERROR: $arcFailMsg"
  Write-Host "PROGRESS: ERROR: Install/repair AutoCAD Express Tools (ctextapp.arx) for the selected AutoCAD Core Console."
  $arcFailMsg | Out-File $logFile -Append
  "Install/repair AutoCAD Express Tools and verify ctextapp.arx can be loaded by accoreconsole." | Out-File $logFile -Append
}
if ($oleRefreshFailures.Count) {
  $oleFails = @($oleRefreshFailures | Select-Object -Unique)
  $oleFailMsg = "Linked Excel OLE refresh did not complete; stale drawings were not plotted: $($oleFails -join ', ')"
  Write-Host "PROGRESS: ERROR: $oleFailMsg"
  $oleFailMsg | Out-File $logFile -Append
}
if ($noPdfOutputFailures.Count) {
  $noPdfFails = @($noPdfOutputFailures | Select-Object -Unique)
  $noPdfFailMsg = "One or more files reported plot success but produced zero layout PDFs: $($noPdfFails -join ', ')"
  Write-Host "PROGRESS: ERROR: $noPdfFailMsg"
  $noPdfFailMsg | Out-File $logFile -Append
}
if ($failed.Count) {
  $failedUnique = @($failed | Select-Object -Unique)
  $failMsg = "One or more files failed to plot: $($failedUnique -join ', ')"
  Write-Host "PROGRESS: ERROR: $failMsg"
  $failMsg | Out-File $logFile -Append
}
if ($pdfLayerCleanupFailed) {
  Write-Host "PROGRESS: ERROR: Publish failed because PDF layer cleanup did not complete."
  "Publish failed because PDF layer cleanup did not complete." | Out-File $logFile -Append
}
if ($pdfMergeFailed) {
  Write-Host "PROGRESS: ERROR: Publish failed because PDF merge did not complete."
  "Publish failed because PDF merge did not complete." | Out-File $logFile -Append
}

if (-not [string]::IsNullOrWhiteSpace($finalCombinedPdfPath) -and (Test-Path -Path $finalCombinedPdfPath -PathType Leaf)) {
  Write-Host "PROGRESS: COMBINED_PDF: $finalCombinedPdfPath"
}
Write-Host "PROGRESS: OUTPUT_FOLDER: $batchOutputDir"

if ($failed.Count -or $pdfLayerCleanupFailed -or $pdfMergeFailed) {
  exit 1
}
