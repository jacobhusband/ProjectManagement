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

Write-Host "PROGRESS: Initializing XREF path repair..."

if ($AcadCore -and (Test-Path -LiteralPath $AcadCore -PathType Leaf)) {
  $acadCore = $AcadCore
}
else {
  $acadCore = $null
  foreach ($year in (2026..2018)) {
    $candidate = "C:\Program Files\Autodesk\AutoCAD $year\accoreconsole.exe"
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
      $acadCore = $candidate
      Write-Host "PROGRESS: Found AutoCAD $year Core Console."
      break
    }
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
  $promptForm.add_Shown({ $selectButton.PerformClick() })
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

function Get-StatusSummary {
  param([object[]]$Occurrences)

  $statusOrder = @("Not Found", "Found", "Orphaned")
  $parts = @()
  foreach ($status in $statusOrder) {
    $count = @($Occurrences | Where-Object { $_.Status -eq $status }).Count
    if ($count -gt 0) {
      $parts += if ($Occurrences.Count -eq $count) { $status } else { "$status ($count)" }
    }
  }
  return ($parts -join ", ")
}

function Get-PathSummary {
  param([object[]]$Occurrences)

  $paths = @(
    $Occurrences |
      ForEach-Object { ([string]$_.SavedPath).Trim() } |
      Where-Object { $_ } |
      Sort-Object -Unique
  )
  if ($paths.Count -eq 0) { return "<empty>" }
  if ($paths.Count -eq 1) { return $paths[0] }
  return "<$($paths.Count) different saved paths>"
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

(defun c:ACIESXREFSCAN (/ outputPath output block flags name savedPath dependent resolved overlay databaseAvailable tab)
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
                (setq name (_acies-safe-field (cdr (assoc 2 block))))
                (setq savedPath (_acies-safe-field (cdr (assoc 1 block))))
                (setq dependent (if (/= 0 (logand flags 16)) "1" "0"))
                (setq resolved (if (/= 0 (logand flags 32)) "1" "0"))
                (setq overlay (if (/= 0 (logand flags 8)) "1" "0"))
                (setq databaseAvailable (_acies-parent-xref-available name))
                (write-line
                  (strcat name tab savedPath tab dependent tab resolved tab overlay tab databaseAvailable)
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
  $scanScript = @(
    "FILEDIA", "0",
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

  for ($index = 0; $index -lt $files.Count; $index++) {
    $dwgPath = [string]$files[$index]
    Write-Host "PROGRESS: Scanning $($index + 1) of $($files.Count): $([IO.Path]::GetFileName($dwgPath))"
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
      $parts = @($line -split "`t", 6)
      while ($parts.Count -lt 6) { $parts += "" }
      $dependent = $parts[2] -eq "1"
      $resolved = $parts[3] -eq "1"
      $databaseAvailable = $parts[5] -eq "1"
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
      $occurrences.Add([pscustomobject]@{
          SourceDwg = $dwgPath
          Name = $parts[0]
          SavedPath = $parts[1]
          Status = $status
          IsDependent = $dependent
          IsResolved = $resolved
          DatabaseAvailable = $databaseAvailable
          IsOverlay = ($parts[4] -eq "1")
          Editable = (-not $dependent)
        })
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
      "Repair XREF Paths",
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

  $groupMap = @{}
  foreach ($occurrence in $occurrences) {
    $key = Get-XrefIdentityKey -Occurrence $occurrence
    if (-not $groupMap.ContainsKey($key)) {
      $displayName = ""
      try { $displayName = [IO.Path]::GetFileName([string]$occurrence.SavedPath) } catch {}
      if ([string]::IsNullOrWhiteSpace($displayName)) { $displayName = [string]$occurrence.Name }
      $groupMap[$key] = [pscustomobject]@{
        Key = $key
        DisplayName = $displayName
        Occurrences = New-Object 'System.Collections.Generic.List[object]'
        NewPath = ""
      }
    }
    $groupMap[$key].Occurrences.Add($occurrence)
  }

  $groups = @(
    $groupMap.Values |
      ForEach-Object {
        # Windows PowerShell 5.1 throws "Argument types do not match" when a
        # generic List[object] is wrapped directly in @(...). Enumerating it
        # through the pipeline produces a normal object array safely.
        $items = @($_.Occurrences | ForEach-Object { $_ })
        $editableCount = @($items | Where-Object { $_.Editable }).Count
        $drawingNames = @($items | ForEach-Object { [IO.Path]::GetFileName($_.SourceDwg) } | Sort-Object -Unique)
        Add-Member -InputObject $_ -NotePropertyName StatusSummary -NotePropertyValue (Get-StatusSummary -Occurrences $items) -Force
        Add-Member -InputObject $_ -NotePropertyName SavedPathSummary -NotePropertyValue (Get-PathSummary -Occurrences $items) -Force
        Add-Member -InputObject $_ -NotePropertyName EditableCount -NotePropertyValue $editableCount -Force
        Add-Member -InputObject $_ -NotePropertyName DrawingCount -NotePropertyValue $drawingNames.Count -Force
        Add-Member -InputObject $_ -NotePropertyName DrawingNames -NotePropertyValue ($drawingNames -join ", ") -Force
        $_
      } |
      Sort-Object @{ Expression = {
        if ($_.StatusSummary -like "Not Found*") { 0 }
        elseif ($_.StatusSummary -like "*Not Found*") { 1 }
        elseif ($_.EditableCount -gt 0) { 2 }
        else { 3 }
      } }, DisplayName
  )

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

  $intro = New-Object System.Windows.Forms.Label
  $intro.Location = New-Object System.Drawing.Point(14, 12)
  $intro.Size = New-Object System.Drawing.Size(1214, 42)
  $intro.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
  $intro.Text = "Each referenced DWG appears once. Choose a replacement to update that saved path in every editable host drawing. Found paths may also be changed. Nested and orphaned references are shown for context but must be repaired in their parent DWG."
  $form.Controls.Add($intro)

  $summary = New-Object System.Windows.Forms.Label
  $summary.Location = New-Object System.Drawing.Point(14, 56)
  $summary.Size = New-Object System.Drawing.Size(1214, 24)
  $summary.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
  $summary.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
  $summary.Text = "$($groups.Count) unique XREF(s) across $($files.Count) drawing(s)."
  if ($scanFailures.Count -gt 0) {
    $summary.Text += " $($scanFailures.Count) drawing(s) could not be scanned."
    $summary.ForeColor = [System.Drawing.Color]::DarkRed
  }
  $form.Controls.Add($summary)

  $grid = New-Object System.Windows.Forms.DataGridView
  $grid.Location = New-Object System.Drawing.Point(14, 84)
  $grid.Size = New-Object System.Drawing.Size(1214, 520)
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
    @{ Name = "Status"; Header = "Status"; Weight = 13 },
    @{ Name = "Xref"; Header = "XREF"; Weight = 17 },
    @{ Name = "SavedPath"; Header = "Current Saved Path"; Weight = 29 },
    @{ Name = "Drawings"; Header = "Occurrences"; Weight = 13 },
    @{ Name = "NewPath"; Header = "New Saved Path"; Weight = 23 }
  )
  foreach ($spec in $columnSpecs) {
    $column = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
    $column.Name = $spec.Name
    $column.HeaderText = $spec.Header
    $column.FillWeight = $spec.Weight
    $column.ReadOnly = $true
    $column.SortMode = [System.Windows.Forms.DataGridViewColumnSortMode]::Automatic
    [void]$grid.Columns.Add($column)
  }
  $chooseColumn = New-Object System.Windows.Forms.DataGridViewButtonColumn
  $chooseColumn.Name = "Choose"
  $chooseColumn.HeaderText = ""
  $chooseColumn.Text = "Choose..."
  $chooseColumn.UseColumnTextForButtonValue = $true
  $chooseColumn.FillWeight = 8
  $chooseColumn.ReadOnly = $false
  [void]$grid.Columns.Add($chooseColumn)

  foreach ($group in $groups) {
    $occurrenceLabel = if ($group.EditableCount -eq $group.Occurrences.Count) {
      "$($group.Occurrences.Count) in $($group.DrawingCount) DWG(s)"
    }
    else {
      "$($group.EditableCount) editable / $($group.Occurrences.Count) total"
    }
    $rowIndex = $grid.Rows.Add(
      $group.StatusSummary,
      $group.DisplayName,
      $group.SavedPathSummary,
      $occurrenceLabel,
      "",
      "Choose..."
    )
    $row = $grid.Rows[$rowIndex]
    $row.Tag = $group
    $row.Cells["SavedPath"].ToolTipText = $group.SavedPathSummary
    $row.Cells["Drawings"].ToolTipText = $group.DrawingNames
    if ($group.StatusSummary -like "*Not Found*" -or $group.StatusSummary -like "*Orphaned*") {
      $row.Cells["Status"].Style.ForeColor = [System.Drawing.Color]::DarkRed
      $row.Cells["Status"].Style.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    }
    if ($group.EditableCount -eq 0) {
      $row.DefaultCellStyle.ForeColor = [System.Drawing.SystemColors]::GrayText
      $row.Cells["Choose"] = New-Object System.Windows.Forms.DataGridViewTextBoxCell
      $row.Cells["Choose"].Value = "Read only"
      $row.Cells["Choose"].ReadOnly = $true
      $row.Cells["NewPath"].Value = "Nested/orphaned - edit parent DWG"
    }
  }
  $form.Controls.Add($grid)

  $clearButton = New-Object System.Windows.Forms.Button
  $clearButton.Text = "Clear Selected Replacement"
  $clearButton.Size = New-Object System.Drawing.Size(205, 38)
  $clearButton.Location = New-Object System.Drawing.Point(14, 618)
  $clearButton.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left
  $form.Controls.Add($clearButton)

  $applyButton = New-Object System.Windows.Forms.Button
  $applyButton.Text = "Apply Selected Paths"
  $applyButton.Size = New-Object System.Drawing.Size(190, 42)
  $applyButton.Location = New-Object System.Drawing.Point(838, 614)
  $applyButton.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Right
  $applyButton.Font = New-Object System.Drawing.Font("Segoe UI", 9.5, [System.Drawing.FontStyle]::Bold)
  $applyButton.Enabled = $false
  $form.Controls.Add($applyButton)

  $cancelButton = New-Object System.Windows.Forms.Button
  $cancelButton.Text = "Cancel"
  $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
  $cancelButton.Size = New-Object System.Drawing.Size(190, 42)
  $cancelButton.Location = New-Object System.Drawing.Point(1038, 614)
  $cancelButton.Anchor = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Right
  $form.Controls.Add($cancelButton)
  $form.CancelButton = $cancelButton

  $refreshApplyButton = {
    $selectedCount = @($groups | Where-Object { -not [string]::IsNullOrWhiteSpace($_.NewPath) }).Count
    $applyButton.Enabled = $selectedCount -gt 0
    $applyButton.Text = if ($selectedCount -gt 0) { "Apply Selected Paths ($selectedCount)" } else { "Apply Selected Paths" }
  }

  $grid.add_CellContentClick({
      param($sender, $eventArgs)
      if ($eventArgs.RowIndex -lt 0 -or $eventArgs.ColumnIndex -lt 0) { return }
      if ($grid.Columns[$eventArgs.ColumnIndex].Name -ne "Choose") { return }
      $row = $grid.Rows[$eventArgs.RowIndex]
      $group = $row.Tag
      if ($null -eq $group -or $group.EditableCount -eq 0) { return }

      $dialog = New-Object System.Windows.Forms.OpenFileDialog
      $dialog.Title = "Choose replacement DWG for $($group.DisplayName)"
      $dialog.Filter = "DWG files (*.dwg)|*.dwg"
      $dialog.Multiselect = $false
      $dialog.CheckFileExists = $true
      $dialog.CheckPathExists = $true
      $dialog.RestoreDirectory = $true
      $candidateDirectory = ""
      if (-not [string]::IsNullOrWhiteSpace($group.NewPath)) {
        $candidateDirectory = Get-ParentDirectory -Path $group.NewPath
      }
      if (-not $candidateDirectory) {
        $candidateDirectory = Get-ParentDirectory -Path ([string]$group.Occurrences[0].SourceDwg)
      }
      $dialog.InitialDirectory = Resolve-DialogInitialDirectory -CandidatePath $candidateDirectory -FallbackPath $inputFolder
      if ($dialog.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {
        $group.NewPath = [IO.Path]::GetFullPath($dialog.FileName)
        $row.Cells["NewPath"].Value = $group.NewPath
        $row.Cells["NewPath"].ToolTipText = $group.NewPath
        & $refreshApplyButton
      }
    })

  $clearButton.add_Click({
      foreach ($row in @($grid.SelectedRows)) {
        $group = $row.Tag
        if ($null -eq $group -or $group.EditableCount -eq 0) { continue }
        $group.NewPath = ""
        $row.Cells["NewPath"].Value = ""
        $row.Cells["NewPath"].ToolTipText = ""
      }
      & $refreshApplyButton
    })

  $applyButton.add_Click({
      $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
      $form.Close()
    })

  $form.add_Shown({
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

  $selectedGroups = @($groups | Where-Object { -not [string]::IsNullOrWhiteSpace($_.NewPath) })
  if ($selectedGroups.Count -eq 0) {
    Write-Host "PROGRESS: No replacement paths were selected."
    exit 0
  }

  $plansByDwg = @{}
  foreach ($group in $selectedGroups) {
    foreach ($occurrence in @($group.Occurrences | Where-Object { $_.Editable })) {
      $dwgKey = ([string]$occurrence.SourceDwg).ToLowerInvariant()
      if (-not $plansByDwg.ContainsKey($dwgKey)) {
        $plansByDwg[$dwgKey] = [pscustomobject]@{
          SourceDwg = [string]$occurrence.SourceDwg
          Updates = New-Object 'System.Collections.Generic.List[object]'
        }
      }
      $existing = @($plansByDwg[$dwgKey].Updates | Where-Object { $_.Name -ieq $occurrence.Name })
      if ($existing.Count -eq 0) {
        $plansByDwg[$dwgKey].Updates.Add([pscustomobject]@{
            Name = [string]$occurrence.Name
            NewPath = [string]$group.NewPath
          })
      }
    }
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

(defun _acies-update-path (name newPath / entity record flags pathPair changedRecord actual)
  (setq entity (tblobjname "BLOCK" name))
  (if (null entity)
    (list "NOT_FOUND" "")
    (progn
      (setq record (entget entity))
      (setq flags (_acies-flags record))
      (cond
        ((= 0 (logand flags 12))
          (list "NOT_XREF" "")
        )
        ((/= 0 (logand flags 16))
          (list "READ_ONLY_DEPENDENT" (if (assoc 1 record) (cdr (assoc 1 record)) ""))
        )
        ((and (assoc 1 record) (= (strcase (cdr (assoc 1 record))) (strcase newPath)))
          (list "ALREADY_SET" (cdr (assoc 1 record)))
        )
        (T
          (setq pathPair (assoc 1 record))
          (setq changedRecord
            (if pathPair
              (subst (cons 1 newPath) pathPair record)
              (append record (list (cons 1 newPath)))
            )
          )
          (if (entmod changedRecord)
            (progn
              (setq actual (cdr (assoc 1 (entget entity))))
              (if (and actual (= (strcase actual) (strcase newPath)))
                (list "UPDATED" actual)
                (list "VERIFY_FAILED" (if actual actual ""))
              )
            )
            (list "UPDATE_FAILED" (if pathPair (cdr pathPair) ""))
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
    "FILEDIA", "0",
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
