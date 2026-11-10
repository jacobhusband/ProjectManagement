param(
  [string]$AcadCore,
  [string]$FilesListPath = "",
  [string]$DefaultDirectory = ""
)

$ErrorActionPreference = "Stop"
$ProcessTimeoutSeconds = 180

# Surface otherwise-unhandled PowerShell failures through the same progress
# channel the desktop app displays in its Activity panel.
trap {
  $message = $_.Exception.Message
  if ([string]::IsNullOrWhiteSpace($message)) { $message = $_.ToString() }
  $lineNumber = $_.InvocationInfo.ScriptLineNumber
  if ($lineNumber) { $message += " (script line $lineNumber)" }
  Write-Host "PROGRESS: ERROR: XREF path repair failed: $message"
  if (-not [string]::IsNullOrWhiteSpace($_.ScriptStackTrace)) {
    Write-Host "PROGRESS: TRACE stack=$($_.ScriptStackTrace -replace '[\r\n]+', ' <- ')"
  }
  exit 1
}

function Get-ParentDirectory {
  param([string]$Path)

  if ([string]::IsNullOrWhiteSpace($Path)) { return "" }
  try { return [IO.Path]::GetDirectoryName($Path) }
  catch { return "" }
}

function Resolve-DialogInitialDirectory {
  param(
    [string]$CandidatePath,
    [string]$FallbackPath = ""
  )

  if ([string]::IsNullOrWhiteSpace($CandidatePath)) { return $FallbackPath }
  $resolvedPath = $CandidatePath.Trim()
  if (Test-Path -LiteralPath $resolvedPath -PathType Leaf) {
    $resolvedPath = Get-ParentDirectory -Path $resolvedPath
  }
  if (Test-Path -LiteralPath $resolvedPath -PathType Container) {
    return $resolvedPath
  }
  return $FallbackPath
}

# The project's Xrefs folder: the nearest "Xrefs" folder beside the host
# drawing's folder or one of its parents (<Project>\Electrical -> <Project>\Xrefs).
function Find-ProjectXrefsFolder {
  param([string]$HostDwg)

  $folder = Get-ParentDirectory -Path $HostDwg
  while (-not [string]::IsNullOrWhiteSpace($folder)) {
    $candidate = Join-Path $folder "Xrefs"
    if (Test-Path -LiteralPath $candidate -PathType Container) { return $candidate }
    $parent = Get-ParentDirectory -Path $folder
    if ($parent -eq $folder) { break }
    $folder = $parent
  }
  return ""
}

Write-Host "PROGRESS: Initializing XREF path repair..."

if ($AcadCore -and (Test-Path -LiteralPath $AcadCore -PathType Leaf)) {
  $acadCore = $AcadCore
}
else {
  $acadCore = $null
  . (Join-Path $PSScriptRoot 'AutoCadDiscovery.ps1')
  $acadInstalls = @(Find-AcadCoreConsole)
  if ($acadInstalls.Count) {
    # Newest release first.
    $acadCore = $acadInstalls[0].Path
    Write-Host "PROGRESS: Found AutoCAD $($acadInstalls[0].Year) Core Console."
  }
}

if (-not $acadCore) {
  Write-Host "PROGRESS: ERROR: AutoCAD Core Console was not found."
  exit 1
}

# WinForms dialogs must run in an STA process. The app launches PowerShell with
# an argv array, so forwarding raw values here preserves paths containing spaces.
if ([System.Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
  $ps = (Get-Process -Id $PID).Path
  $argsList = @("-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", $PSCommandPath)
  if ($AcadCore) { $argsList += @("-AcadCore", $AcadCore) }
  if ($PSBoundParameters.ContainsKey('FilesListPath') -and -not [string]::IsNullOrWhiteSpace($FilesListPath)) {
    $argsList += @("-FilesListPath", $FilesListPath)
  }
  if ($PSBoundParameters.ContainsKey('DefaultDirectory') -and -not [string]::IsNullOrWhiteSpace($DefaultDirectory)) {
    $argsList += @("-DefaultDirectory", $DefaultDirectory)
  }
  $child = Start-Process -FilePath $ps -ArgumentList $argsList -Wait -PassThru
  exit $child.ExitCode
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# The desktop app starts this script with SW_HIDE to keep the console out of
# sight, and Windows applies that to the first window the script shows as well.
# Without an explicit show, that dialog stays invisible and the tool waits forever.
function Show-FormWindow {
  param([System.Windows.Forms.Form]$TargetForm)

  if ($null -eq $TargetForm) { return }
  if (-not ('AciesUi.NativeWindow' -as [type])) {
    Add-Type -Namespace AciesUi -Name NativeWindow -MemberDefinition '[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);'
  }
  [void][AciesUi.NativeWindow]::ShowWindow($TargetForm.Handle, 5)  # SW_SHOW
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
  # Automated runs (tests, CI) set ACIES_NONINTERACTIVE=1. Nobody can answer a
  # picker there, and it would open in the last folder PowerShell used.
  if ($env:ACIES_NONINTERACTIVE -eq '1') {
    Write-Host "PROGRESS: Skipped the file picker because ACIES_NONINTERACTIVE is set."
    return @()
  }
  $promptForm = New-Object System.Windows.Forms.Form
  $promptForm.Text = "Select DWG files to scan for XREFs"
  $promptForm.StartPosition = "CenterScreen"
  $promptForm.Size = New-Object System.Drawing.Size(580, 190)
  $promptForm.MinimumSize = $promptForm.Size
  $promptForm.MaximumSize = $promptForm.Size
  $promptForm.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
  $promptForm.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Font
  $promptForm.MaximizeBox = $false
  $promptForm.MinimizeBox = $false
  $promptForm.TopMost = $true
  $promptForm.ShowInTaskbar = $true

  $label = New-Object System.Windows.Forms.Label
  $label.Text = "Choose one or more host DWGs. Their XREF definitions will be scanned before any drawing is changed."
  $label.Location = New-Object System.Drawing.Point(16, 16)
  $label.Size = New-Object System.Drawing.Size(540, 52)
  $promptForm.Controls.Add($label)

  $selectButton = New-Object System.Windows.Forms.Button
  $selectButton.Text = "Select DWG Files..."
  $selectButton.Size = New-Object System.Drawing.Size(210, 44)
  $selectButton.Location = New-Object System.Drawing.Point(242, 92)
  $selectButton.Font = New-Object System.Drawing.Font("Segoe UI", 9.5, [System.Drawing.FontStyle]::Bold)
  $promptForm.Controls.Add($selectButton)

  $exitButton = New-Object System.Windows.Forms.Button
  $exitButton.Text = "Exit"
  $exitButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
  $exitButton.Size = New-Object System.Drawing.Size(100, 44)
  $exitButton.Location = New-Object System.Drawing.Point(458, 92)
  $promptForm.Controls.Add($exitButton)

  $dialog = New-Object System.Windows.Forms.OpenFileDialog
  $dialog.Title = "Select host DWG files"
  $dialog.Filter = "DWG files (*.dwg)|*.dwg"
  $dialog.Multiselect = $true
  $dialog.CheckFileExists = $true
  $dialog.CheckPathExists = $true
  $dialog.RestoreDirectory = $true
  $dialog.InitialDirectory = Resolve-DialogInitialDirectory -CandidatePath $DefaultDirectory

  $selectButton.add_Click({
      $result = $dialog.ShowDialog($promptForm)
      if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.FileNames.Count -gt 0) {
        $promptForm.Tag = [string[]]$dialog.FileNames
        $promptForm.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $promptForm.Close()
      }
      else {
        $promptForm.Activate()
        $promptForm.BringToFront()
      }
    })
  $promptForm.add_Shown({
      Show-FormWindow $promptForm
      $selectButton.PerformClick()
    })
  $promptForm.AcceptButton = $selectButton
  $promptForm.CancelButton = $exitButton

  if ($promptForm.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
    return @($promptForm.Tag)
  }
  return @()
}

$files = @()
$filesListWasProvided = $PSBoundParameters.ContainsKey('FilesListPath')
Write-Host "PROGRESS: TRACE files_list_param_bound=$([int]$filesListWasProvided) path=$FilesListPath"
if ($filesListWasProvided -and -not [string]::IsNullOrWhiteSpace($FilesListPath)) {
  Write-Host "PROGRESS: Received selected files list: $FilesListPath"
  if (Test-Path -LiteralPath $FilesListPath -PathType Leaf) {
    $files = @(
      Get-Content -LiteralPath $FilesListPath -Encoding UTF8 |
        ForEach-Object { $_.ToString().Trim() } |
        Where-Object {
          $_ -and
          (Test-Path -LiteralPath $_ -PathType Leaf) -and
          ([IO.Path]::GetExtension($_) -ieq ".dwg")
        } |
        ForEach-Object { [IO.Path]::GetFullPath($_) } |
        Select-Object -Unique
    )
  }
}

if ($files.Count -gt 0) {
  Write-Host "PROGRESS: TRACE branch=auto_selected_files count=$($files.Count)"
  Write-Host "PROGRESS: Using $($files.Count) selected DWG file(s)."
}
else {
  Write-Host "PROGRESS: TRACE branch=manual_picker"
  Write-Host "PROGRESS: Waiting for user input..."
  $files = @(Show-DwgFileSelectionPrompt)
  if ($files.Count -eq 0) { exit 0 }
}

$inputFolder = Get-ParentDirectory -Path ([string]$files[0])
if ($inputFolder) {
  Write-Host "PROGRESS: INPUT_FOLDER: $inputFolder"
}

function Stop-ProcessTree {
  param([int]$ProcessId)
  try { & taskkill /PID $ProcessId /T /F | Out-Null } catch {
    try { Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue } catch {}
  }
}

function Invoke-AcadCore {
  param(
    [Parameter(Mandatory = $true)][string]$DwgPath,
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [Parameter(Mandatory = $true)][string]$OutLog,
    [Parameter(Mandatory = $true)][string]$ErrLog,
    [int]$TimeoutSeconds = 180
  )

  $process = Start-Process -FilePath $acadCore `
    -ArgumentList "/i `"$DwgPath`" /s `"$ScriptPath`"" `
    -PassThru -NoNewWindow `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog

  if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
    Stop-ProcessTree -ProcessId $process.Id
    return @{ TimedOut = $true; ExitCode = $null }
  }
  $null = $process.WaitForExit()
  try { $process.Refresh() } catch {}
  $exitCode = $null
  try { if ($process.HasExited) { $exitCode = $process.ExitCode } } catch {}
  return @{ TimedOut = $false; ExitCode = $exitCode }
}

function Test-XrefSavedPathFound {
  param(
    [string]$SourceDwg,
    [string]$SavedPath,
    [bool]$AutoCadResolved
  )

  if ($AutoCadResolved) { return $true }
  if ([string]::IsNullOrWhiteSpace($SavedPath)) { return $false }
  try {
    $expandedPath = [Environment]::ExpandEnvironmentVariables($SavedPath.Trim())
    if ([IO.Path]::IsPathRooted($expandedPath)) {
      return Test-Path -LiteralPath $expandedPath -PathType Leaf
    }
    $hostFolder = Get-ParentDirectory -Path $SourceDwg
    return Test-Path -LiteralPath (Join-Path $hostFolder $expandedPath) -PathType Leaf
  }
  catch {
    return $false
  }
}

# The DWG an XREF's saved path points at, or "" when it is not on disk. AutoCAD
# also finds a moved XREF sitting beside the host drawing, so that is checked too.
function Resolve-XrefFilePath {
  param(
    [string]$SourceDwg,
    [string]$SavedPath
  )

  if ([string]::IsNullOrWhiteSpace($SavedPath)) { return "" }
  try {
    $expandedPath = [Environment]::ExpandEnvironmentVariables($SavedPath.Trim())
    $hostFolder = Get-ParentDirectory -Path $SourceDwg
    $candidates = @()
    if ([IO.Path]::IsPathRooted($expandedPath)) { $candidates += $expandedPath }
    elseif ($hostFolder) { $candidates += (Join-Path $hostFolder $expandedPath) }
    $leafName = [IO.Path]::GetFileName($expandedPath)
    if ($leafName -and $hostFolder) { $candidates += (Join-Path $hostFolder $leafName) }
    foreach ($candidate in $candidates) {
      if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        return [IO.Path]::GetFullPath($candidate)
      }
    }
  }
  catch {}
  return ""
}

function Get-XrefIdentityKey {
  param([object]$Occurrence)

  $leafName = ""
  try { $leafName = [IO.Path]::GetFileName([string]$Occurrence.SavedPath) } catch {}
  if ([string]::IsNullOrWhiteSpace($leafName)) {
    $nameParts = @(([string]$Occurrence.Name) -split '\|')
    $leafName = [string]$nameParts[-1]
  }
  if ([string]::IsNullOrWhiteSpace($leafName)) {
    $leafName = [string]$Occurrence.Name
  }
  return $leafName.Trim().ToLowerInvariant()
}


$toolBase = Join-Path $env:LOCALAPPDATA "AcadHeadlessTools"
if (-not (Test-Path -LiteralPath $toolBase -PathType Container)) {
  New-Item -Path $toolBase -ItemType Directory -Force | Out-Null
}
$tempRoot = Join-Path $toolBase ("XrefPathRepair-" + [guid]::NewGuid().ToString("N"))
New-Item -Path $tempRoot -ItemType Directory -Force | Out-Null

try {
  $scanLspPath = Join-Path $tempRoot "scan_xrefs.lsp"
  $scanScrPath = Join-Path $tempRoot "scan_xrefs.scr"
  $scanLspForAcad = $scanLspPath -replace '\\', '/'

  $scanLisp = @'
(vl-load-com)

(defun _acies-safe-field (value / text)
  (setq text (if value value ""))
  (vl-string-translate (strcat (chr 9) (chr 10) (chr 13)) "   " text)
)

(defun _acies-parent-xref-available (name / separator parentName parentRecord parentFlags)
  (setq separator (vl-string-search "|" name))
  (if (null separator)
    "0"
    (progn
      (setq parentName (substr name 1 separator))
      (setq parentRecord (tblsearch "BLOCK" parentName))
      (setq parentFlags (if parentRecord (cdr (assoc 70 parentRecord)) 0))
      (if (and parentRecord (/= 0 (logand parentFlags 32))) "1" "0")
    )
  )
)

; AutoCAD does not flag a nested XREF: its definition looks like a directly
; attached one. The difference is that the host drawing holds no block
; reference to it; the only references sit inside the parent XREF.
(defun _acies-has-host-reference (name / blockEntity recordEntity record item found)
  (setq blockEntity (tblobjname "BLOCK" name))
  (if blockEntity
    (progn
      (setq recordEntity (cdr (assoc 330 (entget blockEntity))))
      (setq record (if recordEntity (entget recordEntity)))
      (foreach item record
        (if (and (not found) (= 331 (car item)) (entget (cdr item)))
          (setq found T)
        )
      )
    )
  )
  (if found "1" "0")
)

(defun c:ACIESXREFSCAN (/ outputPath output block flags name rawName savedPath dependent resolved overlay databaseAvailable hostReference tab)
  (setq outputPath (getenv "ACIES_XREF_SCAN_OUT"))
  (if outputPath
    (progn
      (setq output (open outputPath "w"))
      (if output
        (progn
          (setq tab (chr 9))
          (setq block (tblnext "BLOCK" T))
          (while block
            (setq flags (cdr (assoc 70 block)))
            (if (null flags) (setq flags 0))
            (if (/= 0 (logand flags 12))
              (progn
                (setq rawName (cdr (assoc 2 block)))
                (setq name (_acies-safe-field rawName))
                (setq hostReference (_acies-has-host-reference rawName))
                (setq savedPath (_acies-safe-field (cdr (assoc 1 block))))
                (setq dependent (if (/= 0 (logand flags 16)) "1" "0"))
                (setq resolved (if (/= 0 (logand flags 32)) "1" "0"))
                (setq overlay (if (/= 0 (logand flags 8)) "1" "0"))
                (setq databaseAvailable (_acies-parent-xref-available name))
                (write-line
                  (strcat name tab savedPath tab dependent tab resolved tab overlay tab databaseAvailable tab hostReference)
                  output
                )
              )
            )
            (setq block (tblnext "BLOCK"))
          )
          (close output)
        )
      )
    )
  )
  (princ)
)
(princ)
'@
  Set-Content -LiteralPath $scanLspPath -Value $scanLisp -Encoding ASCII
  # Scripts already use command-line file prompts. Leave registry-backed FILEDIA alone.
  $scanScript = @(
    "CMDDIA", "0",
    "PROXYNOTICE", "0",
    "SECURELOAD", "0",
    "(load `"$scanLspForAcad`")",
    "ACIESXREFSCAN",
    "_.QUIT", "_N"
  )
  Set-Content -LiteralPath $scanScrPath -Value ($scanScript -join "`r`n") -Encoding ASCII

  $occurrences = New-Object 'System.Collections.Generic.List[object]'
  $scanFailures = New-Object 'System.Collections.Generic.List[string]'

  # The selected drawings are scanned first, then every DWG they reference. A
  # nested XREF's saved path lives in its parent DWG, so the parent has to be
  # scanned (and later saved) for that path to be listed and changed.
  $drawings = @{}
  $scanQueue = New-Object 'System.Collections.Generic.Queue[object]'
  foreach ($file in $files) {
    $drawingKey = ([string]$file).ToLowerInvariant()
    if ($drawings.ContainsKey($drawingKey)) { continue }
    $drawings[$drawingKey] = [pscustomobject]@{
      Key = $drawingKey
      Path = [string]$file
      IsSelected = $true
      ReferencedBy = ""
      Children = New-Object 'System.Collections.Generic.List[string]'
    }
    $scanQueue.Enqueue($drawings[$drawingKey])
  }

  $scanIndex = 0
  while ($scanQueue.Count -gt 0) {
    $drawing = $scanQueue.Dequeue()
    $scanIndex++
    $dwgPath = [string]$drawing.Path
    $scanLabel = [IO.Path]::GetFileName($dwgPath)
    if (-not $drawing.IsSelected) { $scanLabel += " (referenced by $($drawing.ReferencedBy))" }
    Write-Host "PROGRESS: Scanning $scanIndex of $($scanIndex + $scanQueue.Count): $scanLabel"
    $scanOutput = Join-Path $tempRoot ("scan-" + [guid]::NewGuid().ToString("N") + ".tsv")
    $outLog = Join-Path $tempRoot "scan.out.txt"
    $errLog = Join-Path $tempRoot "scan.err.txt"
    $env:ACIES_XREF_SCAN_OUT = $scanOutput
    $result = Invoke-AcadCore -DwgPath $dwgPath -ScriptPath $scanScrPath -OutLog $outLog -ErrLog $errLog -TimeoutSeconds $ProcessTimeoutSeconds
    Remove-Item Env:\ACIES_XREF_SCAN_OUT -ErrorAction SilentlyContinue

    if ($result.TimedOut -or -not (Test-Path -LiteralPath $scanOutput -PathType Leaf)) {
      $scanFailures.Add([IO.Path]::GetFileName($dwgPath))
      continue
    }

    foreach ($line in @(Get-Content -LiteralPath $scanOutput -Encoding ASCII)) {
      if ([string]::IsNullOrWhiteSpace($line)) { continue }
      $parts = @($line -split "`t", 7)
      while ($parts.Count -lt 7) { $parts += "" }
      $dependent = $parts[2] -eq "1"
      $resolved = $parts[3] -eq "1"
      $databaseAvailable = $parts[5] -eq "1"
      $hasHostReference = $parts[6] -eq "1"
      $found = Test-XrefSavedPathFound -SourceDwg $dwgPath -SavedPath $parts[1] -AutoCadResolved ($resolved -or $databaseAvailable)
      $status = if ($dependent) {
        if ($databaseAvailable) { "Found" } else { "Orphaned" }
      }
      elseif ($found) {
        "Found"
      }
      else {
        "Not Found"
      }
      $occurrence = [pscustomobject]@{
        SourceDwg = $dwgPath
        DrawingKey = [string]$drawing.Key
        Name = $parts[0]
        SavedPath = $parts[1]
        Status = $status
        IsDependent = $dependent
        IsResolved = $resolved
        DatabaseAvailable = $databaseAvailable
        IsOverlay = ($parts[4] -eq "1")
        HasHostReference = $hasHostReference
        Editable = (-not $dependent)
        ReadOnlyReason = ""
        IdentityKey = ""
        NewPath = ""
      }
      $occurrence.IdentityKey = Get-XrefIdentityKey -Occurrence $occurrence
      $occurrences.Add($occurrence)

      # Follow only XREFs this drawing places itself. A nested XREF's path is
      # relative to its parent DWG, which is followed in its own right.
      if ($dependent -or -not $hasHostReference) { continue }
      $targetPath = Resolve-XrefFilePath -SourceDwg $dwgPath -SavedPath $parts[1]
      if (-not $targetPath -or [IO.Path]::GetExtension($targetPath) -ine ".dwg") { continue }
      $targetKey = $targetPath.ToLowerInvariant()
      if (-not $drawing.Children.Contains($targetKey)) { $drawing.Children.Add($targetKey) }
      if (-not $drawings.ContainsKey($targetKey)) {
        $drawings[$targetKey] = [pscustomobject]@{
          Key = $targetKey
          Path = $targetPath
          IsSelected = $false
          ReferencedBy = [IO.Path]::GetFileName($dwgPath)
          Children = New-Object 'System.Collections.Generic.List[string]'
        }
        $scanQueue.Enqueue($drawings[$targetKey])
      }
    }
  }

  if ($occurrences.Count -eq 0) {
    $message = if ($scanFailures.Count -gt 0) {
      "No XREF definitions were read. $($scanFailures.Count) drawing(s) could not be scanned."
    }
    else {
      "No XREF definitions were found in the selected drawings."
    }
    [System.Windows.Forms.MessageBox]::Show(
      $message,
      "XREF",
      [System.Windows.Forms.MessageBoxButtons]::OK,
      [System.Windows.Forms.MessageBoxIcon]::Information
    ) | Out-Null
    if ($scanFailures.Count -gt 0) {
      Write-Host "PROGRESS: ERROR: $message"
      exit 1
    }
    Write-Host "PROGRESS: $message"
    exit 0
  }

  # XREF names each drawing places itself, and the drawings reachable from it.
  $placedNamesByDrawing = @{}
  foreach ($occurrence in $occurrences) {
    if (-not $occurrence.HasHostReference) { continue }
    if (-not $placedNamesByDrawing.ContainsKey($occurrence.DrawingKey)) {
      $placedNamesByDrawing[$occurrence.DrawingKey] = @{}
    }
    $placedNamesByDrawing[$occurrence.DrawingKey][([string]$occurrence.Name).ToLowerInvariant()] = $true
  }
  $referencedKeysByDrawing = @{}
  foreach ($drawingKey in @($drawings.Keys)) {
    $reached = @{}
    $pending = New-Object 'System.Collections.Generic.Queue[string]'
    foreach ($childKey in $drawings[$drawingKey].Children) { $pending.Enqueue($childKey) }
    while ($pending.Count -gt 0) {
      $nextKey = $pending.Dequeue()
      if ($nextKey -eq $drawingKey -or $reached.ContainsKey($nextKey)) { continue }
      $reached[$nextKey] = $true
      if ($drawings.ContainsKey($nextKey)) {
        foreach ($childKey in $drawings[$nextKey].Children) { $pending.Enqueue($childKey) }
      }
    }
    $referencedKeysByDrawing[$drawingKey] = $reached
  }

  # One row for every XREF in every drawing. A nested XREF is left out of the
  # host's rows when its parent DWG was scanned: it is listed there instead,
  # where a new path is actually saved. A path set on it in the host is
  # discarded the next time the host loads the parent.
  $xrefRows = New-Object 'System.Collections.Generic.List[object]'
  foreach ($occurrence in $occurrences) {
    if ($occurrence.IsDependent) {
      $occurrence.ReadOnlyReason = "Nested - repair it in its parent DWG"
    }
    elseif (-not $occurrence.HasHostReference) {
      $nameKey = ([string]$occurrence.Name).ToLowerInvariant()
      $listedUnderParent = $false
      foreach ($referencedKey in $referencedKeysByDrawing[$occurrence.DrawingKey].Keys) {
        if ($placedNamesByDrawing.ContainsKey($referencedKey) -and $placedNamesByDrawing[$referencedKey].ContainsKey($nameKey)) {
          $listedUnderParent = $true
          break
        }
      }
      if ($listedUnderParent) { continue }
      $occurrence.Editable = $false
      $occurrence.ReadOnlyReason = "Not placed in this DWG - repair its parent XREF first"
    }
    $xrefRows.Add($occurrence)
  }

  $notFoundKeys = @{}
  foreach ($occurrence in $xrefRows) {
    if ($occurrence.Status -ne "Found") { $notFoundKeys[$occurrence.IdentityKey] = $true }
  }
  $sortedRows = @(
    $xrefRows |
      Sort-Object @{ Expression = { if ($notFoundKeys.ContainsKey($_.IdentityKey)) { 0 } else { 1 } } },
        IdentityKey,
        @{ Expression = { if ($drawings[$_.DrawingKey].IsSelected) { 0 } else { 1 } } },
        SourceDwg
  )
  $listedDrawingCount = @($sortedRows | ForEach-Object { $_.DrawingKey } | Sort-Object -Unique).Count
  $referencedDrawingCount = @($drawings.Values | Where-Object { -not $_.IsSelected }).Count
  $notFoundRowCount = @($sortedRows | Where-Object { $_.Status -ne "Found" }).Count

  $form = New-Object System.Windows.Forms.Form
  $form.Text = "Repair XREF Saved Paths"
  $form.Size = New-Object System.Drawing.Size(1260, 720)
  $form.MinimumSize = New-Object System.Drawing.Size(980, 560)
  $form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Font
  $form.TopMost = $true
  $form.ShowInTaskbar = $true
  $form.MaximizeBox = $true
  $form.MinimizeBox = $false
  Move-FormToPrimaryScreen $form

  $anchorTopWide = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
  $anchorTopLeft = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left
  $anchorBottomLeft = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left
  $anchorBottomRight = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Right

  $intro = New-Object System.Windows.Forms.Label
  $intro.Location = New-Object System.Drawing.Point(14, 12)
  $intro.Size = New-Object System.Drawing.Size(1214, 42)
  $intro.Anchor = $anchorTopWide
  $intro.Text = "Every XREF is listed for each drawing that saves its path, including the DWGs your drawings reference (nested XREFs are listed under their parent DWG). Click Choose... or type a path in New Saved Path. To set several rows at once, select them and click Choose Path for Selected Rows."
  $form.Controls.Add($intro)

  $summary = New-Object System.Windows.Forms.Label
  $summary.Location = New-Object System.Drawing.Point(14, 56)
  $summary.Size = New-Object System.Drawing.Size(1214, 24)
  $summary.Anchor = $anchorTopWide
  $summary.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
  $summary.Text = "$($sortedRows.Count) XREF(s) in $listedDrawingCount drawing(s), $notFoundRowCount not found."
  if ($referencedDrawingCount -gt 0) {
    $summary.Text += " Scanned $($files.Count) selected and $referencedDrawingCount referenced drawing(s)."
  }
  if ($scanFailures.Count -gt 0) {
    $summary.Text += " $($scanFailures.Count) drawing(s) could not be scanned."
    $summary.ForeColor = [System.Drawing.Color]::DarkRed
  }
  $form.Controls.Add($summary)

  $filterLabel = New-Object System.Windows.Forms.Label
  $filterLabel.Text = "Filter:"
  $filterLabel.Location = New-Object System.Drawing.Point(14, 90)
  $filterLabel.Size = New-Object System.Drawing.Size(44, 22)
  $filterLabel.Anchor = $anchorTopLeft
  $form.Controls.Add($filterLabel)

  $filterBox = New-Object System.Windows.Forms.TextBox
  $filterBox.Location = New-Object System.Drawing.Point(60, 87)
  $filterBox.Size = New-Object System.Drawing.Size(250, 24)
  $filterBox.Anchor = $anchorTopLeft
  $form.Controls.Add($filterBox)

  $notFoundCheck = New-Object System.Windows.Forms.CheckBox
  $notFoundCheck.Text = "Show only XREFs that are not found"
  $notFoundCheck.Location = New-Object System.Drawing.Point(326, 87)
  $notFoundCheck.Size = New-Object System.Drawing.Size(260, 24)
  $notFoundCheck.Anchor = $anchorTopLeft
  $form.Controls.Add($notFoundCheck)

  $sameXrefCheck = New-Object System.Windows.Forms.CheckBox
  $sameXrefCheck.Text = "Give a new path to the same XREF in every drawing"
  $sameXrefCheck.Checked = $true
  $sameXrefCheck.Location = New-Object System.Drawing.Point(596, 87)
  $sameXrefCheck.Size = New-Object System.Drawing.Size(400, 24)
  $sameXrefCheck.Anchor = $anchorTopLeft
  $form.Controls.Add($sameXrefCheck)

  $grid = New-Object System.Windows.Forms.DataGridView
  $grid.Location = New-Object System.Drawing.Point(14, 118)
  $grid.Size = New-Object System.Drawing.Size(1214, 486)
  $grid.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
  $grid.AllowUserToAddRows = $false
  $grid.AllowUserToDeleteRows = $false
  $grid.AllowUserToOrderColumns = $true
  $grid.AllowUserToResizeRows = $false
  $grid.AutoSizeRowsMode = [System.Windows.Forms.DataGridViewAutoSizeRowsMode]::AllCells
  $grid.AutoSizeColumnsMode = [System.Windows.Forms.DataGridViewAutoSizeColumnsMode]::Fill
  $grid.BackgroundColor = [System.Drawing.SystemColors]::Window
  $grid.BorderStyle = [System.Windows.Forms.BorderStyle]::Fixed3D
  $grid.MultiSelect = $true
  $grid.ReadOnly = $false
  $grid.RowHeadersVisible = $false
  $grid.SelectionMode = [System.Windows.Forms.DataGridViewSelectionMode]::FullRowSelect
  $grid.ShowCellToolTips = $true

  $columnSpecs = @(
    @{ Name = "Status"; Header = "Status"; Weight = 8 },
    @{ Name = "Xref"; Header = "XREF"; Weight = 15 },
    @{ Name = "Drawing"; Header = "In Drawing"; Weight = 19 },
    @{ Name = "SavedPath"; Header = "Current Saved Path"; Weight = 26 },
    @{ Name = "NewPath"; Header = "New Saved Path"; Weight = 25 }
  )
  foreach ($spec in $columnSpecs) {
    $column = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
    $column.Name = $spec.Name
    $column.HeaderText = $spec.Header
    $column.FillWeight = $spec.Weight
    $column.ReadOnly = ($spec.Name -ne "NewPath")
    $column.SortMode = [System.Windows.Forms.DataGridViewColumnSortMode]::Automatic
    [void]$grid.Columns.Add($column)
  }
  $chooseColumn = New-Object System.Windows.Forms.DataGridViewButtonColumn
  $chooseColumn.Name = "Choose"
  $chooseColumn.HeaderText = ""
  $chooseColumn.Text = "Choose..."
  $chooseColumn.UseColumnTextForButtonValue = $true
  $chooseColumn.FillWeight = 7
  $chooseColumn.ReadOnly = $false
  [void]$grid.Columns.Add($chooseColumn)

  foreach ($occurrence in $sortedRows) {
    $drawingName = [IO.Path]::GetFileName([string]$occurrence.SourceDwg)
    $drawingInfo = $drawings[$occurrence.DrawingKey]
    $drawingLabel = if ($drawingInfo.IsSelected) { $drawingName } else { "$drawingName (referenced by $($drawingInfo.ReferencedBy))" }
    $xrefLabel = [string]$occurrence.Name
    if ($occurrence.IsOverlay) { $xrefLabel += " (overlay)" }
    $savedPathLabel = if ([string]::IsNullOrWhiteSpace($occurrence.SavedPath)) { "<empty>" } else { [string]$occurrence.SavedPath }
    $rowIndex = $grid.Rows.Add(
      $occurrence.Status,
      $xrefLabel,
      $drawingLabel,
      $savedPathLabel,
      "",
      "Choose..."
    )
    $row = $grid.Rows[$rowIndex]
    $row.Tag = $occurrence
    $row.Cells["SavedPath"].ToolTipText = $savedPathLabel
    $row.Cells["Drawing"].ToolTipText = [string]$occurrence.SourceDwg
    if ($occurrence.Status -ne "Found") {
      $row.Cells["Status"].Style.ForeColor = [System.Drawing.Color]::DarkRed
      $row.Cells["Status"].Style.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    }
    if (-not $occurrence.Editable) {
      $row.DefaultCellStyle.ForeColor = [System.Drawing.SystemColors]::GrayText
      $row.Cells["Choose"] = New-Object System.Windows.Forms.DataGridViewTextBoxCell
      $row.Cells["Choose"].Value = "Read only"
      $row.Cells["Choose"].ReadOnly = $true
      $row.Cells["NewPath"].Value = $occurrence.ReadOnlyReason
      $row.Cells["NewPath"].ReadOnly = $true
    }
  }
  $form.Controls.Add($grid)

  $clearButton = New-Object System.Windows.Forms.Button
  $clearButton.Text = "Clear Selected Rows"
  $clearButton.Size = New-Object System.Drawing.Size(170, 38)
  $clearButton.Location = New-Object System.Drawing.Point(14, 618)
  $clearButton.Anchor = $anchorBottomLeft
  $form.Controls.Add($clearButton)

  $chooseSelectedButton = New-Object System.Windows.Forms.Button
  $chooseSelectedButton.Text = "Choose Path for Selected Rows..."
  $chooseSelectedButton.Size = New-Object System.Drawing.Size(250, 38)
  $chooseSelectedButton.Location = New-Object System.Drawing.Point(194, 618)
  $chooseSelectedButton.Anchor = $anchorBottomLeft
  $form.Controls.Add($chooseSelectedButton)

  $applyButton = New-Object System.Windows.Forms.Button
  $applyButton.Text = "Apply New Paths"
  $applyButton.Size = New-Object System.Drawing.Size(190, 42)
  $applyButton.Location = New-Object System.Drawing.Point(838, 614)
  $applyButton.Anchor = $anchorBottomRight
  $applyButton.Font = New-Object System.Drawing.Font("Segoe UI", 9.5, [System.Drawing.FontStyle]::Bold)
  $applyButton.Enabled = $false
  $form.Controls.Add($applyButton)

  $cancelButton = New-Object System.Windows.Forms.Button
  $cancelButton.Text = "Cancel"
  $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
  $cancelButton.Size = New-Object System.Drawing.Size(190, 42)
  $cancelButton.Location = New-Object System.Drawing.Point(1038, 614)
  $cancelButton.Anchor = $anchorBottomRight
  $form.Controls.Add($cancelButton)
  $form.CancelButton = $cancelButton

  $refreshApplyButton = {
    $changedRows = @($sortedRows | Where-Object { $_.Editable -and -not [string]::IsNullOrWhiteSpace($_.NewPath) })
    $changedDrawings = @($changedRows | ForEach-Object { $_.DrawingKey } | Sort-Object -Unique).Count
    $applyButton.Enabled = $changedRows.Count -gt 0
    $applyButton.Text = if ($changedRows.Count -gt 0) { "Apply New Paths ($($changedRows.Count))" } else { "Apply New Paths" }
    $form.Text = if ($changedRows.Count -gt 0) {
      "Repair XREF Saved Paths - $($changedRows.Count) change(s) in $changedDrawings drawing(s)"
    }
    else {
      "Repair XREF Saved Paths"
    }
  }

  # Stores a new path on one row. A path that cannot be found from the row's
  # drawing is still accepted, but shown in red.
  $setRowNewPath = {
    param($row, [string]$newPath)
    $occurrence = $row.Tag
    if ($null -eq $occurrence -or -not $occurrence.Editable) { return }
    $occurrence.NewPath = $newPath
    $cell = $row.Cells["NewPath"]
    $cell.Value = $newPath
    $cell.ToolTipText = $newPath
    $cell.Style.ForeColor = [System.Drawing.Color]::Empty
    if ($newPath -and -not (Test-XrefSavedPathFound -SourceDwg $occurrence.SourceDwg -SavedPath $newPath -AutoCadResolved $false)) {
      $cell.Style.ForeColor = [System.Drawing.Color]::DarkRed
      $cell.ToolTipText = "$newPath - no file is at this path from this drawing's folder"
    }
  }

  # The rows a new path on $row goes to: the row itself and, while the box is
  # ticked, the same XREF in every other drawing.
  $getRowsSharingPath = {
    param($row)
    $targets = New-Object 'System.Collections.Generic.List[object]'
    $targets.Add($row)
    if ($sameXrefCheck.Checked -and $null -ne $row.Tag) {
      foreach ($otherRow in $grid.Rows) {
        if ($otherRow.Index -eq $row.Index -or $null -eq $otherRow.Tag) { continue }
        if ($otherRow.Tag.Editable -and $otherRow.Tag.IdentityKey -eq $row.Tag.IdentityKey) {
          $targets.Add($otherRow)
        }
      }
    }
    return , @($targets | ForEach-Object { $_ })
  }

  $pickReplacementPath = {
    param($occurrence, [string]$title)
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = $title
    $dialog.Filter = "DWG files (*.dwg)|*.dwg"
    $dialog.Multiselect = $false
    $dialog.CheckFileExists = $true
    $dialog.CheckPathExists = $true
    $dialog.RestoreDirectory = $true
    $candidateDirectory = ""
    if (-not [string]::IsNullOrWhiteSpace($occurrence.NewPath) -and [IO.Path]::IsPathRooted($occurrence.NewPath)) {
      $candidateDirectory = Get-ParentDirectory -Path $occurrence.NewPath
    }
    if (-not $candidateDirectory) {
      $candidateDirectory = Find-ProjectXrefsFolder -HostDwg ([string]$occurrence.SourceDwg)
    }
    if (-not $candidateDirectory) {
      $candidateDirectory = Get-ParentDirectory -Path ([string]$occurrence.SourceDwg)
    }
    $dialog.InitialDirectory = Resolve-DialogInitialDirectory -CandidatePath $candidateDirectory -FallbackPath $inputFolder
    if ($dialog.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
      return [IO.Path]::GetFullPath($dialog.FileName)
    }
    return ""
  }

  $grid.add_CellContentClick({
      param($sender, $eventArgs)
      if ($eventArgs.RowIndex -lt 0 -or $eventArgs.ColumnIndex -lt 0) { return }
      if ($grid.Columns[$eventArgs.ColumnIndex].Name -ne "Choose") { return }
      $row = $grid.Rows[$eventArgs.RowIndex]
      $occurrence = $row.Tag
      if ($null -eq $occurrence -or -not $occurrence.Editable) { return }

      $chosenPath = & $pickReplacementPath $occurrence "Choose replacement DWG for $($occurrence.Name)"
      if ($chosenPath) {
        foreach ($targetRow in (& $getRowsSharingPath $row)) { & $setRowNewPath $targetRow $chosenPath }
        & $refreshApplyButton
      }
    })

  # Typing in New Saved Path works like Choose..., and also takes a relative
  # path such as ..\Xrefs\A01-00.dwg. Clearing the cell drops the change.
  $grid.add_CellEndEdit({
      param($sender, $eventArgs)
      if ($eventArgs.RowIndex -lt 0 -or $eventArgs.ColumnIndex -lt 0) { return }
      if ($grid.Columns[$eventArgs.ColumnIndex].Name -ne "NewPath") { return }
      $row = $grid.Rows[$eventArgs.RowIndex]
      $occurrence = $row.Tag
      if ($null -eq $occurrence -or -not $occurrence.Editable) { return }

      $typedPath = ([string]$row.Cells["NewPath"].Value).Trim().Trim('"').Replace('/', '\')
      if ($typedPath -eq [string]$occurrence.NewPath) {
        & $setRowNewPath $row $typedPath
        return
      }
      if ($typedPath -and $typedPath -notmatch '\.dwg$') {
        & $setRowNewPath $row ([string]$occurrence.NewPath)
        [System.Windows.Forms.MessageBox]::Show(
          $form,
          "An XREF path has to end in .dwg.",
          "XREF",
          [System.Windows.Forms.MessageBoxButtons]::OK,
          [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
        return
      }
      foreach ($targetRow in (& $getRowsSharingPath $row)) { & $setRowNewPath $targetRow $typedPath }
      & $refreshApplyButton
    })

  $chooseSelectedButton.add_Click({
      $targetRows = @($grid.SelectedRows | Where-Object { $_.Visible -and $null -ne $_.Tag -and $_.Tag.Editable })
      if ($targetRows.Count -eq 0) {
        [System.Windows.Forms.MessageBox]::Show(
          $form,
          "Select one or more rows first. Hold Ctrl or Shift to select several.",
          "XREF",
          [System.Windows.Forms.MessageBoxButtons]::OK,
          [System.Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
        return
      }
      $chosenPath = & $pickReplacementPath $targetRows[0].Tag "Choose replacement DWG for $($targetRows.Count) selected row(s)"
      if ($chosenPath) {
        foreach ($targetRow in $targetRows) { & $setRowNewPath $targetRow $chosenPath }
        & $refreshApplyButton
      }
    })

  $clearButton.add_Click({
      foreach ($row in @($grid.SelectedRows)) { & $setRowNewPath $row "" }
      & $refreshApplyButton
    })

  $applyFilter = {
    $needle = $filterBox.Text.Trim().ToLowerInvariant()
    [void]$grid.EndEdit()
    $grid.CurrentCell = $null
    foreach ($row in $grid.Rows) {
      $occurrence = $row.Tag
      if ($null -eq $occurrence) { continue }
      $visible = -not ($notFoundCheck.Checked -and $occurrence.Status -eq "Found")
      if ($visible -and $needle) {
        $haystack = "$($occurrence.Name) $($occurrence.SavedPath) $($occurrence.SourceDwg) $($occurrence.NewPath)".ToLowerInvariant()
        $visible = $haystack.Contains($needle)
      }
      $row.Visible = $visible
    }
  }
  $filterBox.add_TextChanged({ & $applyFilter })
  $notFoundCheck.add_CheckedChanged({ & $applyFilter })

  $applyButton.add_Click({
      $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
      $form.Close()
    })

  $form.add_Shown({
      Show-FormWindow $form
      $form.Activate()
      $form.BringToFront()
    })

  Write-Host "PROGRESS: Waiting for XREF path selections..."
  Write-Host "PROGRESS: XREF path dialog should be visible on the primary display."
  Write-Host "PROGRESS: TRACE branch=xref_path_selection_dialog"
  if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    Write-Host "PROGRESS: XREF path repair cancelled."
    exit 0
  }

  $changedOccurrences = @($sortedRows | Where-Object { $_.Editable -and -not [string]::IsNullOrWhiteSpace($_.NewPath) })
  if ($changedOccurrences.Count -eq 0) {
    Write-Host "PROGRESS: No replacement paths were selected."
    exit 0
  }

  $plansByDwg = @{}
  foreach ($occurrence in $changedOccurrences) {
    $dwgKey = [string]$occurrence.DrawingKey
    if (-not $plansByDwg.ContainsKey($dwgKey)) {
      $plansByDwg[$dwgKey] = [pscustomobject]@{
        SourceDwg = [string]$occurrence.SourceDwg
        Updates = New-Object 'System.Collections.Generic.List[object]'
      }
    }
    $plansByDwg[$dwgKey].Updates.Add([pscustomobject]@{
        Name = [string]$occurrence.Name
        NewPath = [string]$occurrence.NewPath
      })
  }

  $updateLspPath = Join-Path $tempRoot "update_xrefs.lsp"
  $updateScrPath = Join-Path $tempRoot "update_xrefs.scr"
  $updateLspForAcad = $updateLspPath -replace '\\', '/'
  $updateLisp = @'
(vl-load-com)

(defun _acies-read-plan (path / file line tabPos items)
  (setq file (open path "r"))
  (if file
    (progn
      (while (setq line (read-line file))
        (setq tabPos (vl-string-search (chr 9) line))
        (if tabPos
          (setq items
            (cons
              (cons (substr line 1 tabPos) (substr line (+ tabPos 2)))
              items
            )
          )
        )
      )
      (close file)
      (reverse items)
    )
  )
)

(defun _acies-flags (record / pair)
  (setq pair (assoc 70 record))
  (if pair (cdr pair) 0)
)

(defun _acies-saved-path (record)
  (if (and record (assoc 1 record)) (cdr (assoc 1 record)) "")
)

; -XREF reads the name as a wildcard pattern, so "A1.0" would also match
; "A1-0" and a comma would split it into two names. Backquote escapes each
; special character.
(defun _acies-escape-wildcards (text / result index char)
  (setq result "")
  (setq index 1)
  (while (<= index (strlen text))
    (setq char (substr text index 1))
    (if (vl-string-search char "#@.*?~[]-,`")
      (setq result (strcat result "`" char))
      (setq result (strcat result char))
    )
    (setq index (1+ index))
  )
  result
)

; entmod cannot change the saved path of an XREF block definition (it returns
; nil), so the path goes through -XREF _Path, which also reloads the XREF.
(defun _acies-update-path (name newPath / record flags oldPath actual)
  (setq record (tblsearch "BLOCK" name))
  (if (null record)
    (list "NOT_FOUND" "")
    (progn
      (setq flags (_acies-flags record))
      (setq oldPath (_acies-saved-path record))
      (cond
        ((= 0 (logand flags 12))
          (list "NOT_XREF" "")
        )
        ((/= 0 (logand flags 16))
          (list "READ_ONLY_DEPENDENT" oldPath)
        )
        ((= (strcase oldPath) (strcase newPath))
          (list "ALREADY_SET" oldPath)
        )
        (T
          (command "_.-XREF" "_Path" (_acies-escape-wildcards name) newPath)
          ; Bit 1 only: the script that runs this command sets bit 4 for its
          ; whole run, and Enter at the Command prompt repeats the last command.
          (while (= 1 (logand 1 (getvar "CMDACTIVE"))) (command ""))
          (setq actual (_acies-saved-path (tblsearch "BLOCK" name)))
          (cond
            ((= (strcase actual) (strcase newPath))
              (list "UPDATED" actual)
            )
            ((= (strcase actual) (strcase oldPath))
              (list "UPDATE_FAILED" actual)
            )
            (T
              (list "VERIFY_FAILED" actual)
            )
          )
        )
      )
    )
  )
)

(defun c:ACIESXREFUPDATE (/ planPath reportPath plan report tab item result saveStatus)
  (setq planPath (getenv "ACIES_XREF_UPDATE_PLAN"))
  (setq reportPath (getenv "ACIES_XREF_UPDATE_OUT"))
  (setq tab (chr 9))
  (setq plan (_acies-read-plan planPath))
  (setq report (open reportPath "w"))
  (if report
    (progn
      (foreach item plan
        (setq result (_acies-update-path (car item) (cdr item)))
        (write-line
          (strcat (car item) tab (car result) tab (cadr result))
          report
        )
      )
      (command "_.QSAVE")
      (setq saveStatus (if (= (getvar "DBMOD") 0) "SAVE_OK" "SAVE_FAILED"))
      (write-line (strcat "<DWG_SAVE>" tab saveStatus tab "") report)
      (close report)
    )
  )
  (princ)
)
(princ)
'@
  Set-Content -LiteralPath $updateLspPath -Value $updateLisp -Encoding ASCII
  $updateScript = @(
    "CMDDIA", "0",
    "PROXYNOTICE", "0",
    "SECURELOAD", "0",
    "(load `"$updateLspForAcad`")",
    "ACIESXREFUPDATE",
    "_.QUIT", "_N"
  )
  Set-Content -LiteralPath $updateScrPath -Value ($updateScript -join "`r`n") -Encoding ASCII

  $plans = @($plansByDwg.Values | Sort-Object SourceDwg)
  $updatedCount = 0
  $failedDrawings = New-Object 'System.Collections.Generic.List[string]'
  for ($planIndex = 0; $planIndex -lt $plans.Count; $planIndex++) {
    $plan = $plans[$planIndex]
    $dwgName = [IO.Path]::GetFileName([string]$plan.SourceDwg)
    Write-Host "PROGRESS: Updating $($planIndex + 1) of $($plans.Count): $dwgName"
    $planPath = Join-Path $tempRoot ("plan-" + [guid]::NewGuid().ToString("N") + ".tsv")
    $reportPath = Join-Path $tempRoot ("update-" + [guid]::NewGuid().ToString("N") + ".tsv")
    @($plan.Updates | ForEach-Object { "$($_.Name)`t$($_.NewPath)" }) |
      Set-Content -LiteralPath $planPath -Encoding ASCII
    $env:ACIES_XREF_UPDATE_PLAN = $planPath
    $env:ACIES_XREF_UPDATE_OUT = $reportPath
    $outLog = Join-Path $tempRoot "update.out.txt"
    $errLog = Join-Path $tempRoot "update.err.txt"
    $result = Invoke-AcadCore -DwgPath $plan.SourceDwg -ScriptPath $updateScrPath -OutLog $outLog -ErrLog $errLog -TimeoutSeconds $ProcessTimeoutSeconds
    Remove-Item Env:\ACIES_XREF_UPDATE_PLAN -ErrorAction SilentlyContinue
    Remove-Item Env:\ACIES_XREF_UPDATE_OUT -ErrorAction SilentlyContinue

    $rows = @()
    if (Test-Path -LiteralPath $reportPath -PathType Leaf) {
      $rows = @(
        Get-Content -LiteralPath $reportPath -Encoding ASCII |
          Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
          ForEach-Object {
            $parts = @($_ -split "`t", 3)
            while ($parts.Count -lt 3) { $parts += "" }
            [pscustomobject]@{ Name = $parts[0]; Result = $parts[1]; ActualPath = $parts[2] }
          }
      )
    }

    $saveOkay = @($rows | Where-Object { $_.Name -eq "<DWG_SAVE>" -and $_.Result -eq "SAVE_OK" }).Count -gt 0
    $updatesOkay = $true
    foreach ($expected in $plan.Updates) {
      $match = @($rows | Where-Object {
          $_.Name -ieq $expected.Name -and
          $_.Result -in @("UPDATED", "ALREADY_SET") -and
          $_.ActualPath -ieq $expected.NewPath
        })
      if ($match.Count -eq 0) {
        $updatesOkay = $false
      }
      else {
        $updatedCount++
      }
    }

    if ($result.TimedOut -or -not $saveOkay -or -not $updatesOkay) {
      $failedDrawings.Add($dwgName)
    }
  }

  if ($failedDrawings.Count -gt 0) {
    $failedSummary = ($failedDrawings | Select-Object -First 4) -join ", "
    if ($failedDrawings.Count -gt 4) { $failedSummary += ", +$($failedDrawings.Count - 4) more" }
    Write-Host "PROGRESS: ERROR: XREF paths could not be fully verified in $($failedDrawings.Count) drawing(s): $failedSummary"
    exit 1
  }

  Write-Host "PROGRESS: Updated $updatedCount XREF definition(s) across $($plans.Count) drawing(s)."
}
finally {
  Remove-Item Env:\ACIES_XREF_SCAN_OUT -ErrorAction SilentlyContinue
  Remove-Item Env:\ACIES_XREF_UPDATE_PLAN -ErrorAction SilentlyContinue
  Remove-Item Env:\ACIES_XREF_UPDATE_OUT -ErrorAction SilentlyContinue
  try {
    $resolvedBase = [IO.Path]::GetFullPath($toolBase).TrimEnd('\')
    $resolvedTemp = [IO.Path]::GetFullPath($tempRoot).TrimEnd('\')
    if ($resolvedTemp.StartsWith($resolvedBase + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
      Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction SilentlyContinue
    }
  }
  catch {}
}
