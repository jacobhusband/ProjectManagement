param(
  [string]$AcadCore,
  [string]$DisciplineShort,
  [string]$FilesListPath = "",
  [string]$SourceManifestPath = "",
  [string]$DefaultDirectory = "",
  [int]$StripXrefs = 1,
  [int]$SetByLayer = 1,
  [int]$Purge = 1,
  [int]$Audit = 1,
  [int]$HatchColor = 1,
  [int]$BindExplode = 1,
  [int]$SkipAcad = 0
)

# removeXrefPaths.ps1
# Process DWGs -> accoreconsole loads your .NET DLL via NETLOAD -> runs STRIPREFPATHS
# All feedback is sent to the console for the main application to display.

Write-Host "PROGRESS: Initializing script..."

# --- AUTOCAD VERSION DETECTION ---
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

$scriptRoot = $PSScriptRoot
$dll = Join-Path $scriptRoot "StripRefPaths.dll"

# Validation
if ([string]::IsNullOrEmpty($acadCore) -or -not (Test-Path $acadCore)) {
  Write-Host "PROGRESS: ERROR: AutoCAD Core Console not found for versions 2020-2025."
  Write-Host "Please ensure AutoCAD is installed in the default 'C:\Program Files\Autodesk' directory."
  exit 1
}

if ($StripXrefs -and -not (Test-Path $dll)) {
  Write-Host "PROGRESS: ERROR: Required component 'StripRefPaths.dll' not found at $dll"
  exit 1
}

# Relaunch in STA mode so Windows file dialogs work reliably.
if ([System.Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') {
  $ps = (Get-Process -Id $PID).Path
  $argsList = @("-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
  if ($AcadCore) { $argsList += @("-AcadCore", "`"$AcadCore`"") }
  if ($DisciplineShort) { $argsList += @("-DisciplineShort", "`"$DisciplineShort`"") }
  if ($FilesListPath) { $argsList += @("-FilesListPath", "`"$FilesListPath`"") }
  if ($SourceManifestPath) { $argsList += @("-SourceManifestPath", "`"$SourceManifestPath`"") }
  $argsList += @('-BindExplode', $BindExplode)
  if ($DefaultDirectory) { $argsList += @("-DefaultDirectory", "`"$DefaultDirectory`"") }
  if ($PSBoundParameters.ContainsKey('StripXrefs')) { $argsList += @("-StripXrefs", $StripXrefs) }
  if ($PSBoundParameters.ContainsKey('SetByLayer')) { $argsList += @("-SetByLayer", $SetByLayer) }
  if ($PSBoundParameters.ContainsKey('Purge')) { $argsList += @("-Purge", $Purge) }
  if ($PSBoundParameters.ContainsKey('Audit')) { $argsList += @("-Audit", $Audit) }
  if ($PSBoundParameters.ContainsKey('HatchColor')) { $argsList += @("-HatchColor", $HatchColor) }
  if ($PSBoundParameters.ContainsKey('SkipAcad')) { $argsList += @("-SkipAcad", $SkipAcad) }
  $child = Start-Process -FilePath $ps -ArgumentList $argsList -WindowStyle Hidden -Wait -PassThru
  exit $child.ExitCode
}

Add-Type -AssemblyName System.Windows.Forms

function Get-DisciplineShort([string]$value) {
  $short = ($value -split '[,;/\s]')[0]
  if ([string]::IsNullOrWhiteSpace($short)) { return "E" }
  return $short.Trim().ToUpper()
}

function Join-PathParts([string[]]$parts) {
  if (-not $parts -or $parts.Count -eq 0) { return "" }
  # Filter out empty strings (from UNC path splitting)
  $nonEmpty = $parts | Where-Object { $_ }
  if ($nonEmpty.Count -eq 0) { return "" }

  # Check if original path was UNC (starts with \\)
  # If first two parts were empty, it was a UNC path
  $isUnc = ($parts.Count -ge 2 -and $parts[0] -eq "" -and $parts[1] -eq "")

  if ($isUnc) {
    # Rebuild UNC path: \\server\share\...
    return "\\" + ($nonEmpty -join "\")
  }
  else {
    # Regular path
    $path = $nonEmpty[0]
    for ($i = 1; $i -lt $nonEmpty.Count; $i++) {
      $path = Join-Path -Path $path -ChildPath $nonEmpty[$i]
    }
    return $path
  }
}

function Find-FolderIndex([string[]]$parts, [string]$name) {
  for ($i = 0; $i -lt $parts.Count; $i++) {
    if ($parts[$i] -ieq $name) { return $i }
  }
  return -1
}

function Get-SheetIdFromName([string]$name) {
  # Prefer sheet IDs that start with A (ex: A00-00), then fall back to
  # single-letter dash patterns (ex: E-1-02-100).
  $preferredPattern = '(?i)\bA\d{1,3}-\d{1,3}[A-Z]?\b'
  $preferredMatch = [regex]::Match($name, $preferredPattern)
  if ($preferredMatch.Success) { return $preferredMatch.Value.ToUpper() }

  $fallbackPattern = '(?i)\b[A-Z]-\d{1,3}-\d{2}-\d+\b'
  $fallbackMatch = [regex]::Match($name, $fallbackPattern)
  if ($fallbackMatch.Success) { return $fallbackMatch.Value.ToUpper() }

  return $null
}

function Get-CleanFileName([string]$name) {
  $invalid = [IO.Path]::GetInvalidFileNameChars()
  $clean = $name
  foreach ($char in $invalid) {
    $clean = $clean -replace [regex]::Escape($char), ''
  }
  $clean = $clean.Trim()
  if ([string]::IsNullOrWhiteSpace($clean)) { return "Sheet" }
  return $clean
}

function Ensure-ArchiveDirectory {
  param([Parameter(Mandatory = $true)][string]$TargetDir)

  $archiveDir = Join-Path -Path $TargetDir -ChildPath "Archive"
  if (-not (Test-Path -LiteralPath $archiveDir)) {
    New-Item -Path $archiveDir -ItemType Directory -Force | Out-Null
    Write-Host "PROGRESS: Created Archive folder at $archiveDir"
  }
  return $archiveDir
}

function Move-FileToArchive {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [Parameter(Mandatory = $true)][string]$ArchiveRoot,
    [string]$Message = "Archived existing file to"
  )

  $item = Get-Item -LiteralPath $FilePath -ErrorAction Stop
  $archiveDir = Ensure-ArchiveDirectory -TargetDir $ArchiveRoot
  $timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
  $archiveName = "{0}_{1}{2}" -f $item.BaseName, $timestamp, $item.Extension
  $archivePath = Join-Path -Path $archiveDir -ChildPath $archiveName
  Move-Item -LiteralPath $item.FullName -Destination $archivePath -Force
  Write-Host "PROGRESS: $Message $archiveName"
  return $archivePath
}

function New-IncomingWorkingCopy {
  param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$TargetDir,
    [string]$SourceLabel = "source"
  )

  $incomingName = "__incoming__{0}{1}" -f ([guid]::NewGuid().ToString('N')), [IO.Path]::GetExtension($SourcePath)
  $incomingPath = Join-Path -Path $TargetDir -ChildPath $incomingName
  Copy-Item -LiteralPath $SourcePath -Destination $incomingPath -Force
  Write-Host "PROGRESS: Staged $SourceLabel in Xrefs as $incomingName"
  return $incomingPath
}

function Show-DwgFileDialog {
  param([string]$InitialDirectory = "")
  # Automated runs (tests, CI) set ACIES_NONINTERACTIVE=1. Nobody can answer a
  # picker there, and it would open in the last folder PowerShell used.
  if ($env:ACIES_NONINTERACTIVE -eq '1') {
    Write-Host "PROGRESS: Skipped the file picker because ACIES_NONINTERACTIVE is set."
    return $null
  }

  $dlg = New-Object System.Windows.Forms.OpenFileDialog
  $dlg.Title = "Select DWG files or ZIP archives"
  $dlg.Filter = "DWG files and ZIP archives (*.dwg;*.zip)|*.dwg;*.zip|DWG files (*.dwg)|*.dwg|ZIP archives (*.zip)|*.zip"
  $dlg.Multiselect = $true
  $dlg.CheckFileExists = $true
  $dlg.CheckPathExists = $true
  $dlg.RestoreDirectory = $true
  if ($InitialDirectory -and (Test-Path -LiteralPath $InitialDirectory)) {
    $dlg.InitialDirectory = $InitialDirectory
  }

  $result = $dlg.ShowDialog()
  if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $dlg.FileNames.Count -gt 0) {
    return [string[]]$dlg.FileNames
  }
  return $null
}

function Show-ZipDwgDialog {
  param([Parameter(Mandatory = $true)][string]$ZipPath)
  # Automated runs (tests, CI) set ACIES_NONINTERACTIVE=1. Nobody can answer the
  # ZIP entry list or folder picker there.
  if ($env:ACIES_NONINTERACTIVE -eq '1') {
    Write-Host "PROGRESS: Skipped the ZIP drawing picker because ACIES_NONINTERACTIVE is set."
    return @()
  }

  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
  try {
    $entryNames = @($zip.Entries | Where-Object {
      $_.Name -and ([IO.Path]::GetExtension($_.FullName) -ieq '.dwg')
    } | ForEach-Object { $_.FullName } | Sort-Object)
  }
  finally { $zip.Dispose() }

  if ($entryNames.Count -eq 0) {
    [System.Windows.Forms.MessageBox]::Show("No DWG files were found in $ZipPath", "Select DWGs from ZIP") | Out-Null
    return @()
  }

  $form = New-Object System.Windows.Forms.Form
  try {
    $form.Text = "Select DWGs from $([IO.Path]::GetFileName($ZipPath))"
    $form.Size = New-Object System.Drawing.Size(800, 520)
    $form.MinimumSize = New-Object System.Drawing.Size(600, 350)
    $form.StartPosition = 'CenterScreen'
    $label = New-Object System.Windows.Forms.Label
    $label.Text = 'Check the drawings you want to prepare for XREF. Paths are shown as stored in the ZIP.'
    $label.Dock = 'Top'
    $label.Height = 35
    $list = New-Object System.Windows.Forms.CheckedListBox
    $list.Dock = 'Fill'
    $list.CheckOnClick = $true
    $list.HorizontalScrollbar = $true
    foreach ($entryName in $entryNames) { [void]$list.Items.Add($entryName) }
    $buttons = New-Object System.Windows.Forms.FlowLayoutPanel
    $buttons.Dock = 'Bottom'
    $buttons.Height = 45
    $buttons.FlowDirection = 'RightToLeft'
    $cancel = New-Object System.Windows.Forms.Button
    $cancel.Text = 'Cancel'
    $cancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $ok = New-Object System.Windows.Forms.Button
    $ok.Text = 'Use selected'
    $ok.AutoSize = $true
    $ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $buttons.Controls.Add($cancel)
    $buttons.Controls.Add($ok)
    $form.Controls.Add($list)
    $form.Controls.Add($label)
    $form.Controls.Add($buttons)
    $form.AcceptButton = $ok
    $form.CancelButton = $cancel
    if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return @() }
    $selected = @($list.CheckedItems | ForEach-Object { [string]$_ })
    if ($selected.Count -eq 0) { return @() }

    $projectRoot = Get-ProjectRootFromArchPath -Path $ZipPath
    if (-not $projectRoot) {
      $folder = New-Object System.Windows.Forms.FolderBrowserDialog
      try {
        $folder.Description = 'Select the project root folder. Prepared drawings will go into its Xrefs subfolder.'
        $folder.SelectedPath = Split-Path -Parent $ZipPath
        if ($folder.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return @() }
        $projectRoot = $folder.SelectedPath
      }
      finally { $folder.Dispose() }
    }
    return @($selected | ForEach-Object {
      [pscustomobject]@{
        Kind = 'zipEntry'
        Path = ''
        ZipPath = [IO.Path]::GetFullPath($ZipPath)
        EntryName = $_ -replace '\\', '/'
        ProjectRoot = $projectRoot
        DisplayPath = "${ZipPath}::$_"
      }
    })
  }
  finally { $form.Dispose() }
}

function New-FileSourceItem {
  param([Parameter(Mandatory = $true)][string]$Path)

  return [pscustomobject]@{
    Kind = "file"
    Path = [IO.Path]::GetFullPath($Path)
    ZipPath = ""
    EntryName = ""
    ProjectRoot = ""
    DisplayPath = [IO.Path]::GetFullPath($Path)
  }
}

function Get-SourceItemDisplayPath {
  param([Parameter(Mandatory = $true)]$SourceItem)

  if ($SourceItem.DisplayPath) { return [string]$SourceItem.DisplayPath }
  if ($SourceItem.Kind -eq "zipEntry") {
    return "{0}::{1}" -f $SourceItem.ZipPath, $SourceItem.EntryName
  }
  return [string]$SourceItem.Path
}

function Get-ProjectRootFromArchPath {
  param([string]$Path)

  $parts = ([IO.Path]::GetFullPath($Path)) -split '[\\/]'
  $archIndex = Find-FolderIndex $parts 'Arch'
  if ($archIndex -lt 0) { return "" }
  if ($archIndex -le 0) { return $parts[0] }
  return Join-PathParts $parts[0..($archIndex - 1)]
}

function Read-SourceManifest {
  param([string]$ManifestPath)

  if ([string]::IsNullOrWhiteSpace($ManifestPath) -or -not (Test-Path -LiteralPath $ManifestPath)) {
    return @()
  }

  $rawJson = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8
  if ([string]::IsNullOrWhiteSpace($rawJson)) { return @() }
  $entries = $rawJson | ConvertFrom-Json
  $items = @()
  foreach ($entry in @($entries)) {
    $kind = if ($entry.kind) { [string]$entry.kind } else { "file" }
    if ($kind -eq "zipEntry") {
      $zipPath = [string]$entry.zipPath
      $entryName = ([string]$entry.entryName) -replace '\\', '/'
      if (
        [string]::IsNullOrWhiteSpace($zipPath) -or
        [string]::IsNullOrWhiteSpace($entryName) -or
        -not (Test-Path -LiteralPath $zipPath) -or
        ([IO.Path]::GetExtension($entryName) -ine ".dwg")
      ) {
        continue
      }
      $displayPath = if ($entry.displayPath) { [string]$entry.displayPath } else { "{0}::{1}" -f $zipPath, $entryName }
      $items += [pscustomobject]@{
        Kind = "zipEntry"
        Path = ""
        ZipPath = [IO.Path]::GetFullPath($zipPath)
        EntryName = $entryName
        ProjectRoot = if ($entry.projectRoot) { [IO.Path]::GetFullPath([string]$entry.projectRoot) } else { "" }
        DisplayPath = $displayPath
      }
      continue
    }

    $path = [string]$entry.path
    if (
      [string]::IsNullOrWhiteSpace($path) -or
      -not (Test-Path -LiteralPath $path) -or
      ([IO.Path]::GetExtension($path) -ine ".dwg")
    ) {
      continue
    }
    $item = New-FileSourceItem -Path $path
    if ($entry.projectRoot) {
      $item.ProjectRoot = [IO.Path]::GetFullPath([string]$entry.projectRoot)
    }
    if ($entry.displayPath) {
      $item.DisplayPath = [string]$entry.displayPath
    }
    $items += $item
  }
  return @($items)
}

function Resolve-SourceItemToWorkingSource {
  param(
    [Parameter(Mandatory = $true)]$SourceItem,
    [Parameter(Mandatory = $true)][string]$TempRoot
  )

  if ($SourceItem.Kind -eq "zipEntry") {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [System.IO.Compression.ZipFile]::OpenRead($SourceItem.ZipPath)
    try {
      $entry = $zip.Entries | Where-Object {
        ($_.FullName -replace '\\', '/') -ieq $SourceItem.EntryName
      } | Select-Object -First 1
      if (-not $entry) {
        throw "ZIP entry not found: $($SourceItem.EntryName)"
      }
      $zipKey = [IO.Path]::GetFullPath($SourceItem.ZipPath)
      $extractDir = $script:xrefExtractedArchives[$zipKey]
      if (-not $extractDir) {
        $extractDir = Join-Path $TempRoot ([guid]::NewGuid().ToString("N"))
        New-Item -Path $extractDir -ItemType Directory -Force | Out-Null
        # GetFullPath expands 8.3 names such as C:\Users\ADMINI~1 in %TEMP%. Compare
        # entries against the same long form, or every entry looks like it escapes.
        $extractDir = [IO.Path]::GetFullPath($extractDir)
      # Keep the dependency tree, not just the selected DWG. Validate every path
      # before writing so an archive cannot escape the temporary workspace.
      $destinations = @{}
      $totalBytes = [long]0
      foreach ($member in $zip.Entries) {
        $relative = $member.FullName -replace '/', '\'
        if ([IO.Path]::IsPathRooted($relative) -or $relative.Contains(':') -or
            @($relative.Split('\') | Where-Object { $_ -eq '..' -or $_ -match '[. ]$' }).Count -gt 0) {
          throw "Unsafe ZIP entry: $($member.FullName)"
        }
        $destination = [IO.Path]::GetFullPath((Join-Path $extractDir $relative))
        if (-not $destination.StartsWith($extractDir + '\', [StringComparison]::OrdinalIgnoreCase)) {
          throw "ZIP entry escapes staging folder: $($member.FullName)"
        }
        if (-not $member.Name) { continue }
        if ($destinations.ContainsKey($destination)) { throw "Duplicate ZIP entry: $($member.FullName)" }
        $destinations[$destination] = $true
        $totalBytes += $member.Length
        if ($totalBytes -gt 10GB -or $destinations.Count -gt 50000) { throw 'ZIP exceeds staging limits (10 GB / 50,000 files).' }
        New-Item -Path (Split-Path -Parent $destination) -ItemType Directory -Force | Out-Null
        [System.IO.Compression.ZipFileExtensions]::ExtractToFile($member, $destination, $false)
      }
        $script:xrefExtractedArchives[$zipKey] = $extractDir
      }
      $extractPath = Join-Path $extractDir ($SourceItem.EntryName -replace '/', '\')
      return [pscustomobject]@{
        SourcePath = [IO.Path]::GetFullPath($extractPath)
        SourceLabel = "Arch ZIP source"
        ProjectRoot = if ($SourceItem.ProjectRoot) { [string]$SourceItem.ProjectRoot } else { Get-ProjectRootFromArchPath -Path $SourceItem.ZipPath }
        ForceXrefsTarget = $true
        ArchiveSelectedSource = $false
        SearchRoot = $extractDir
      }
    }
    finally {
      $zip.Dispose()
    }
  }

  return [pscustomobject]@{
    SourcePath = [IO.Path]::GetFullPath([string]$SourceItem.Path)
    SourceLabel = ""
    ProjectRoot = if ($SourceItem.ProjectRoot) { [string]$SourceItem.ProjectRoot } else { "" }
    ForceXrefsTarget = $false
    ArchiveSelectedSource = $false
    SearchRoot = Split-Path -Parent ([string]$SourceItem.Path)
  }
}

function Invoke-AcadCoreScript {
  param(
    [Parameter(Mandatory = $true)][string]$AcadCorePath,
    [Parameter(Mandatory = $true)][string]$DwgPath,
    [Parameter(Mandatory = $true)][string]$ScriptPath,
    [int]$TimeoutSeconds = 600,
    [hashtable]$Environment = @{}
  )

  # accoreconsole blocks forever on any unanswered prompt, which would freeze
  # the whole tool with no error surfaced, so run it through a killable process.
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $AcadCorePath
  $psi.Arguments = ('/i "{0}" /s "{1}"' -f $DwgPath, $ScriptPath)
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.CreateNoWindow = $true
  foreach ($key in $Environment.Keys) { $psi.EnvironmentVariables[$key] = [string]$Environment[$key] }

  $proc = [System.Diagnostics.Process]::Start($psi)
  $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
  $stderrTask = $proc.StandardError.ReadToEndAsync()

  $timedOut = $false
  if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
    $timedOut = $true
    try { $proc.Kill() } catch {}
    $proc.WaitForExit()
  }

  # Stderr is merged into the output so the Python wrapper can catch errors.
  # accoreconsole emits UTF-16 output; strip embedded NULs so pattern matching works.
  $raw = ($stdoutTask.Result + "`n" + $stderrTask.Result) -replace "`0", ''
  $output = @($raw -split "`r?`n" | Where-Object { $_.Length -gt 0 })
  if ($timedOut) {
    $output += "PROGRESS: ERROR: AutoCAD Core Console did not finish within $TimeoutSeconds second(s) for $([IO.Path]::GetFileName($DwgPath)) and was terminated."
  }
  $exitCode = if ($timedOut) { -1 } else { $proc.ExitCode }
  foreach ($line in $output) { Write-Host $line }
  return [pscustomobject]@{
    ExitCode = $exitCode
    Output = $output
  }
}

function Get-AuditErrorCount {
  param([string[]]$OutputLines)

  # Returns the error count from the last AUDIT summary line, or $null if none seen.
  $count = $null
  foreach ($line in @($OutputLines)) {
    $match = [regex]::Match($line, '(?i)Total errors found(?: during audit)?\s+(\d+)')
    if ($match.Success) { $count = [int]$match.Groups[1].Value }
  }
  return $count
}

function Get-AcadOutputFailureSignal {
  param([string[]]$OutputLines)

  # A zero exit code from accoreconsole does not guarantee every command ran;
  # scan the output for signals that NETLOAD/STRIPREFPATHS or another step failed.
  $patterns = @(
    'Unknown command',
    'Unable to load',
    'Cannot load assembly',
    'FATAL ERROR',
    'INTERNAL ERROR'
  )
  foreach ($line in @($OutputLines)) {
    foreach ($pattern in $patterns) {
      if ($line -match [regex]::Escape($pattern)) { return $line.Trim() }
    }
  }
  return $null
}

Write-Host "PROGRESS: Staging cleanup commands..."
# Stage AutoLISP CLEANUP command so each drawing is tidied after ref paths are stripped
$lisp = Join-Path $env:TEMP "cleanup_tmp.lsp"
$setByLayerBlock = ""
if ($SetByLayer) {
  $setByLayerBlock = @'
  ;; Use SETBYLAYER on everything in the current space
  ;;   "Y" => Change ByBlock to ByLayer?
  ;;   "Y" => Include blocks?
  (command
    "_.-SETBYLAYER" "All" "" "Y" "Y")

'@
}

$hatchBlock = ""
if ($HatchColor) {
  $hatchBlock = @'
  ;; Change color of non-nested modelspace hatches to 9 (excluding WALL layers)
  ;; This runs AFTER SETBYLAYER so the color override is preserved
  ;; ssget "X" with filter: HATCH entities in modelspace (410 = "Model")
  ;; Recolor through CHPROP rather than entmod: hand-edited HATCH entity
  ;; lists can leave malformed data that trips AUDIT/recovery on reopen.
  (setq ss (ssget "_X" '((0 . "HATCH") (410 . "Model"))))
  (if ss
    (progn
      (setq target (ssadd))
      (setq i 0)
      (repeat (sslength ss)
        (setq ent (ssname ss i))
        (setq layerName (cdr (assoc 8 (entget ent))))
        ;; Check if layer name does NOT contain "WALL" (case-insensitive)
        (if (not (wcmatch (strcase layerName) "*WALL*"))
          (ssadd ent target)
        )
        (setq i (1+ i))
      )
      (if (> (sslength target) 0)
        (command "_.CHPROP" target "" "_Color" "9" "")
      )
    )
  )

'@
}

$purgeBlock = ""
if ($Purge) {
  $purgeBlock = @'
  ;; Purge the entire drawing; "All", "*" (everything), "No" to confirm each
  (command "_.-PURGE" "All" "*" "N")

'@
}

$auditBlock = ""
if ($Audit) {
  $auditBlock = @'
  ;; Audit the drawing; "Yes" to fix errors
  (command "_.AUDIT" "Y")

'@
}

$lispContent = @"
(defun c:CLEANUP (/ oldCMDECHO oldTab ss target i ent layerName)
  ;; Remember current command echo setting, then turn it off:
  (setq oldCMDECHO (getvar "CMDECHO")
        oldTab     (getvar "CTAB"))
  (setvar "CMDECHO" 0)

  ;; Ensure commands run from Model space (setvar avoids layout-switch
  ;; command quirks in accoreconsole)
  (if (/= oldTab "Model")
    (setvar "CTAB" "Model")
  )

$setByLayerBlock$hatchBlock$purgeBlock$auditBlock
  ;; Restore layout/model state if it changed
  (if (/= oldTab (getvar "CTAB"))
    (setvar "CTAB" oldTab)
  )

  ;; Restore command echo setting
  (setvar "CMDECHO" oldCMDECHO)
  (princ)
)
"@
Set-Content -Encoding ASCII -Path $lisp -Value $lispContent

# Make .scr that runs the requested steps
$script = Join-Path $env:TEMP "run_STRIP.scr"
$lispPathForScript = ($lisp -replace '\\', '/')
$scriptLines = @(
  "CMDECHO 1",
  "FILEDIA 0",
  "SECURELOAD 0"
)
if ($StripXrefs) {
  $scriptLines += "NETLOAD"
  $scriptLines += "`"$dll`""
  $scriptLines += "STRIPREFPATHS"
}

$runCleanup = $SetByLayer -or $Purge -or $Audit -or $HatchColor
if ($runCleanup) {
  $scriptLines += "(load `"$lispPathForScript`")"
  $scriptLines += "CLEANUP"
}

$scriptLines += "QSAVE"
$scriptLines += "QUIT"
$scriptContent = $scriptLines -join "`r`n"
Set-Content -Encoding ASCII -Path $script -Value $scriptContent

# Audit-only script used to verify each processed drawing reopens cleanly.
# "N" answers "Fix any errors detected?" so verification never mutates the file.
# Reopening alone can mark the database modified (xref re-resolution, regen),
# so QUIT must be followed by "_Y" to answer the "Really want to discard all
# changes?" prompt; without it accoreconsole waits on that prompt forever.
$verifyScript = Join-Path $env:TEMP "verify_AUDIT.scr"
$verifyContent = @(
  "CMDECHO 1",
  "FILEDIA 0",
  "_.AUDIT",
  "N",
  "_.QUIT",
  "_Y"
) -join "`r`n"
Set-Content -Encoding ASCII -Path $verifyScript -Value $verifyContent

# Resolve files: prefer workflow source manifest, then preselected list, otherwise open the DWG picker.
$sourceItems = @()
if (-not [string]::IsNullOrWhiteSpace($SourceManifestPath) -and (Test-Path -LiteralPath $SourceManifestPath)) {
  $sourceItems = @(Read-SourceManifest -ManifestPath $SourceManifestPath)
  if ($sourceItems.Count -gt 0) {
    Write-Host "PROGRESS: Using $($sourceItems.Count) DWG source(s) from workflow selection."
  }
  else {
    Write-Host "PROGRESS: Provided source manifest was empty. Opening DWG file picker..."
  }
}
elseif (-not [string]::IsNullOrWhiteSpace($SourceManifestPath)) {
  Write-Host "PROGRESS: Provided source manifest path not found. Opening DWG file picker..."
}

if (($sourceItems.Count -eq 0) -and -not [string]::IsNullOrWhiteSpace($FilesListPath) -and (Test-Path -LiteralPath $FilesListPath)) {
  $filesFromList = @(
    Get-Content -Path $FilesListPath -Encoding UTF8 |
      Where-Object {
        $_ -and
        $_.Trim() -and
        (Test-Path -LiteralPath $_.Trim()) -and
        ([IO.Path]::GetExtension($_.Trim()) -ieq ".dwg")
      } |
      ForEach-Object { [IO.Path]::GetFullPath($_.Trim()) } |
      Select-Object -Unique
  )
  $sourceItems = @($filesFromList | ForEach-Object { New-FileSourceItem -Path $_ })
  if ($sourceItems.Count -gt 0) {
    Write-Host "PROGRESS: Using $($sourceItems.Count) DWG file(s) from auto-selected project folder."
  }
  else {
    Write-Host "PROGRESS: Provided files list was empty. Opening DWG file picker..."
  }
}
elseif (($sourceItems.Count -eq 0) -and -not [string]::IsNullOrWhiteSpace($FilesListPath)) {
  Write-Host "PROGRESS: Provided files list path not found. Opening DWG file picker..."
}

if ($sourceItems.Count -eq 0) {
  Write-Host "PROGRESS: Opening DWG file picker..."
  $sourceSelections = Show-DwgFileDialog -InitialDirectory $DefaultDirectory
  if (-not $sourceSelections -or @($sourceSelections).Count -eq 0) {
    Write-Host "PROGRESS: Cancelled. No files selected."
    return
  }

  $filesFromDialog = @(
    @($sourceSelections) |
      ForEach-Object { $_.ToString().Trim() } |
      Where-Object {
        $_ -and
        (Test-Path -LiteralPath $_) -and
        ([IO.Path]::GetExtension($_) -iin @('.dwg', '.zip'))
      } |
      ForEach-Object { [IO.Path]::GetFullPath($_) } |
      Select-Object -Unique
  )
  $sourceItems = @($filesFromDialog | ForEach-Object {
    if ([IO.Path]::GetExtension($_) -ieq '.zip') {
      Show-ZipDwgDialog -ZipPath $_
    }
    else { New-FileSourceItem -Path $_ }
  })
}

if ($sourceItems.Count -eq 0) {
  Write-Host "PROGRESS: Cancelled. No DWG files selected."
  return
}

$files = @($sourceItems | ForEach-Object { Get-SourceItemDisplayPath -SourceItem $_ })
$inputFolder = ""
if ($sourceItems.Count -gt 0) {
  $firstItem = $sourceItems[0]
  if ($firstItem.Kind -eq "zipEntry") {
    $inputFolder = Split-Path -Path ([string]$firstItem.ZipPath) -Parent
  }
  else {
    $inputFolder = Split-Path -Path ([string]$firstItem.Path) -Parent
  }
}
if (-not [string]::IsNullOrWhiteSpace($inputFolder)) {
  Write-Host "PROGRESS: INPUT_FOLDER: $inputFolder"
}
Write-Host "PROGRESS: Processing $($sourceItems.Count) file(s)..."

$disciplineShort = Get-DisciplineShort $DisciplineShort
$failed = @()
$processed = @()
$comparisonPairs = @()
$i = 0
$sourceTempRoot = Join-Path $env:TEMP ("acies-clean-xrefs-sources-" + [guid]::NewGuid().ToString("N"))
$script:xrefExtractedArchives = @{}
New-Item -Path $sourceTempRoot -ItemType Directory -Force | Out-Null
$outputFolder = ""
try {
  foreach ($sourceItem in $sourceItems) {
    $i++
    $displayPath = Get-SourceItemDisplayPath -SourceItem $sourceItem
    $name = if ($sourceItem.Kind -eq "zipEntry") { [IO.Path]::GetFileName([string]$sourceItem.EntryName) } else { [IO.Path]::GetFileName([string]$sourceItem.Path) }
    Write-Host "PROGRESS: Preparing $i of $($sourceItems.Count): $name"
    $comparisonPairCandidate = $null

    try {
      $resolvedSource = Resolve-SourceItemToWorkingSource -SourceItem $sourceItem -TempRoot $sourceTempRoot
      $fullPath = [IO.Path]::GetFullPath([string]$resolvedSource.SourcePath)
      $parts = $fullPath -split '[\\/]'

      $sourcePath = $fullPath
      $workingPath = $fullPath
      $targetDir = Split-Path -Parent $fullPath
      $stagedInXrefs = $false
      $archiveSelectedSource = [bool]$resolvedSource.ArchiveSelectedSource
      $stageLabel = [string]$resolvedSource.SourceLabel
      $comparisonOldPath = ""

      if ($resolvedSource.ForceXrefsTarget) {
        $projectRoot = [string]$resolvedSource.ProjectRoot
        if ([string]::IsNullOrWhiteSpace($projectRoot)) {
          throw "Project root is required for ZIP XREF source: $displayPath"
        }
        $targetDir = Join-Path -Path $projectRoot -ChildPath "Xrefs"
        if (-not (Test-Path -LiteralPath $targetDir)) {
          New-Item -Path $targetDir -ItemType Directory -Force | Out-Null
          Write-Host "PROGRESS: Created Xrefs folder at $targetDir"
        }
        $stagedInXrefs = $true
        if ([string]::IsNullOrWhiteSpace($stageLabel)) { $stageLabel = "Arch source" }
        Write-Host "PROGRESS: Preparing Arch ZIP source for Xrefs transfer: $name"
      }
      else {
        $xrefIndex = Find-FolderIndex $parts 'Xrefs'
        if ($xrefIndex -lt 0) { $xrefIndex = Find-FolderIndex $parts 'Xref' }
        $archIndex = Find-FolderIndex $parts 'Arch'

        if ($xrefIndex -ge 0) {
          $relativeXrefParts = @()
          if (($xrefIndex + 1) -le ($parts.Count - 2)) {
            $relativeXrefParts = @($parts[($xrefIndex + 1)..($parts.Count - 2)])
          }
          if (@($relativeXrefParts | Where-Object { $_ -ieq 'Archive' }).Count -gt 0) {
            throw "Selected DWG is already inside the Xrefs\Archive folder. Choose a DWG from Arch or the active Xrefs folder instead."
          }

          $targetDir = Join-PathParts $parts[0..$xrefIndex]
          $stagedInXrefs = $true
          $archiveSelectedSource = $true
          $stageLabel = "Xrefs source"
          Write-Host "PROGRESS: Preparing Xrefs source for Xrefs cleanup: $name"
        }
        elseif ($archIndex -ge 0) {
          if ($archIndex -le 0) {
            $projectRoot = $parts[0]
          }
          else {
            $projectRoot = Join-PathParts $parts[0..($archIndex - 1)]
          }
          $targetDir = Join-Path -Path $projectRoot -ChildPath "Xrefs"
          if (-not (Test-Path -LiteralPath $targetDir)) {
            New-Item -Path $targetDir -ItemType Directory -Force | Out-Null
            Write-Host "PROGRESS: Created Xrefs folder at $targetDir"
          }
          $stagedInXrefs = $true
          $stageLabel = "Arch source"
          Write-Host "PROGRESS: Preparing Arch source for Xrefs transfer: $name"
        }
      }

      $baseName = [IO.Path]::GetFileNameWithoutExtension($sourcePath)
      $sheetId = Get-SheetIdFromName $baseName
      if ($sheetId) {
        $targetBase = Get-CleanFileName $sheetId
      }
      else {
        $targetBase = Get-CleanFileName $baseName
      }
      $targetName = "{0} ({1})" -f $targetBase, $disciplineShort
      $targetPath = Join-Path -Path $targetDir -ChildPath "$targetName.dwg"

      # Finish binding on a disposable copy before archiving/replacing anything.
      $transferSource = $sourcePath
      if ($BindExplode -and -not $SkipAcad) {
        $framework = if ([Diagnostics.FileVersionInfo]::GetVersionInfo($acadCore).FileMajorPart -ge 25) { 'net8.0-windows' } else { 'net48' }
        $prepareDll = Join-Path $scriptRoot "PrepareXrefs-bin\$framework\PrepareXrefs.dll"
        if (-not (Test-Path -LiteralPath $prepareDll)) { throw "Missing XREF preparation component: $prepareDll" }
        $prepareDir = Join-Path $sourceTempRoot ([guid]::NewGuid().ToString('N'))
        New-Item -Path $prepareDir -ItemType Directory -Force | Out-Null
        $prepareInput = Join-Path $prepareDir 'input.dwg'
        $prepareOutput = Join-Path $prepareDir 'prepared.dwg'
        Copy-Item -LiteralPath $sourcePath -Destination $prepareInput
        $prepareScript = Join-Path $prepareDir 'prepare.scr'
        @('FILEDIA 0', 'SECURELOAD 0', '_.NETLOAD', ('"' + $prepareDll + '"'),
          'ACIESPREPAREXREFS', '_.QUIT', '_Y') | Set-Content -LiteralPath $prepareScript -Encoding UTF8
        Write-Host "PROGRESS: Binding and exploding modelspace Xrefs in $name..."
        $prepareRun = Invoke-AcadCoreScript -AcadCorePath $acadCore -DwgPath $prepareInput -ScriptPath $prepareScript -Environment @{
          ACIES_XREF_SOURCE = $sourcePath
          ACIES_XREF_OUTPUT = $prepareOutput
          ACIES_XREF_SEARCH_ROOT = $resolvedSource.SearchRoot
          ACIES_XREF_PACKAGE = if ($sourceItem.Kind -eq 'zipEntry') { '1' } else { '0' }
        }
        if ($prepareRun.ExitCode -ne 0 -or -not (Test-Path -LiteralPath ($prepareOutput + '.ready')) -or
            -not (Test-Path -LiteralPath $prepareOutput)) {
          throw 'Binding/exploding failed. Existing Xrefs and source drawings have been preserved. See AutoCAD output above.'
        }
        $transferSource = $prepareOutput
      }

      if ($stagedInXrefs) {
        $workingPath = New-IncomingWorkingCopy -SourcePath $transferSource -TargetDir $targetDir -SourceLabel $stageLabel
        if ($archiveSelectedSource) {
          $archivedSelectedSourcePath = Move-FileToArchive -FilePath $sourcePath -ArchiveRoot $targetDir -Message "Archived selected Xrefs source to"
          if ([string]::Equals(
              [IO.Path]::GetFullPath($sourcePath),
              [IO.Path]::GetFullPath($targetPath),
              [StringComparison]::OrdinalIgnoreCase
            )) {
            $comparisonOldPath = $archivedSelectedSourcePath
          }
        }
        Write-Host "PROGRESS: Final target in Xrefs: $([IO.Path]::GetFileName($targetPath))"
      }
      elseif ($transferSource -ne $sourcePath) {
        $workingPath = New-IncomingWorkingCopy -SourcePath $transferSource -TargetDir $targetDir -SourceLabel 'prepared source'
      }

      $existing = Get-ChildItem -LiteralPath $targetDir -File |
        Where-Object { $_.BaseName -ieq $targetName }
      Write-Host "PROGRESS: Checking exact target-name collisions for '$targetName' in $targetDir"
      foreach ($item in $existing) {
        if ($item.FullName -ne $workingPath) {
          $archivedCollisionPath = Move-FileToArchive -FilePath $item.FullName -ArchiveRoot $targetDir -Message "Archived existing file to"
          if ($item.Extension -ieq ".dwg") {
            # The exact-name DWG is the canonical XREF being replaced. Prefer it
            # over an archived selected source when both paths are present.
            $comparisonOldPath = $archivedCollisionPath
          }
        }
      }

      if ($workingPath -ne $targetPath) {
        Move-Item -LiteralPath $workingPath -Destination $targetPath -Force
        $workingPath = $targetPath
      }
      if ([string]::IsNullOrWhiteSpace($outputFolder)) {
        $outputFolder = Split-Path -Parent ([IO.Path]::GetFullPath($workingPath))
      }

      if (
        -not [string]::IsNullOrWhiteSpace($comparisonOldPath) -and
        (Test-Path -LiteralPath $comparisonOldPath -PathType Leaf) -and
        (Test-Path -LiteralPath $workingPath -PathType Leaf)
      ) {
        $comparisonPairCandidate = [pscustomobject]@{
          NewPath = [IO.Path]::GetFullPath($workingPath)
          OldPath = [IO.Path]::GetFullPath($comparisonOldPath)
          Label = $targetBase
        }
      }
    }
    catch {
      Write-Host "PROGRESS: ERROR: Failed to prepare $name - $_"
      $failed += $displayPath
      continue
    }

    Write-Host "PROGRESS: Processing $i of $($sourceItems.Count): $([IO.Path]::GetFileName($workingPath))"

    if ($SkipAcad) {
      Write-Host "PROGRESS: SkipAcad enabled. Skipping accoreconsole execution for $([IO.Path]::GetFileName($workingPath))."
      if ($null -ne $comparisonPairCandidate) {
        $comparisonPairs += $comparisonPairCandidate
      }
      continue
    }

    # IMPORTANT: no /ld here; we NETLOAD via the .scr
    $acadRun = Invoke-AcadCoreScript -AcadCorePath $acadCore -DwgPath $workingPath -ScriptPath $script
    $workingName = [IO.Path]::GetFileName($workingPath)
    $auditErrors = Get-AuditErrorCount -OutputLines $acadRun.Output
    if ($null -ne $auditErrors -and $auditErrors -gt 0) {
      Write-Host "PROGRESS: WARNING: AUDIT found and fixed $auditErrors error(s) in $workingName."
    }
    $failureSignal = Get-AcadOutputFailureSignal -OutputLines $acadRun.Output
    if ($acadRun.ExitCode -ne 0) {
      Write-Host "PROGRESS: ERROR: AutoCAD Core Console exited with code $($acadRun.ExitCode) for $workingName."
      $failed += $workingPath
    }
    elseif ($failureSignal) {
      Write-Host "PROGRESS: ERROR: AutoCAD reported a problem while processing $workingName - $failureSignal"
      $failed += $workingPath
    }
    else {
      $processed += $workingPath
      if ($null -ne $comparisonPairCandidate) {
        $comparisonPairs += $comparisonPairCandidate
      }
    }
  }
}
finally {
  $resolvedTemp = [IO.Path]::GetFullPath($sourceTempRoot)
  $expectedTempParent = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
  if ($resolvedTemp.StartsWith($expectedTempParent, [StringComparison]::OrdinalIgnoreCase) -and
      [IO.Path]::GetFileName($resolvedTemp).StartsWith('acies-clean-xrefs-sources-')) {
    Remove-Item -LiteralPath $resolvedTemp -Recurse -Force -ErrorAction SilentlyContinue
  }
}

# Reopen each processed drawing and run a read-only AUDIT so corruption that
# would only surface when the user reopens the file is caught right away.
if (-not $SkipAcad -and $processed.Count -gt 0) {
  Write-Host "PROGRESS: Verifying $($processed.Count) drawing(s) reopen cleanly..."
  foreach ($dwg in $processed) {
    $name = [IO.Path]::GetFileName($dwg)
    $verifyRun = Invoke-AcadCoreScript -AcadCorePath $acadCore -DwgPath $dwg -ScriptPath $verifyScript
    $verifyErrors = Get-AuditErrorCount -OutputLines $verifyRun.Output
    if ($verifyRun.ExitCode -ne 0) {
      Write-Host "PROGRESS: ERROR: $name failed to reopen for verification (exit code $($verifyRun.ExitCode))."
      $failed += $dwg
    }
    elseif ($null -eq $verifyErrors) {
      Write-Host "PROGRESS: WARNING: Could not read AUDIT results while verifying $name."
    }
    elseif ($verifyErrors -gt 0) {
      Write-Host "PROGRESS: ERROR: $name still reports $verifyErrors AUDIT error(s) on reopen."
      $failed += $dwg
    }
    else {
      Write-Host "PROGRESS: Verified clean on reopen: $name"
    }
  }
}

Write-Progress -Activity "Processing DWGs" -Completed

if ($failed.Count) {
  Write-Host "PROGRESS: ERROR: $($failed.Count) of $($sourceItems.Count) file(s) failed to process."
}
else {
  Write-Host "PROGRESS: Successfully processed $($sourceItems.Count) drawing(s)."
}

foreach ($pair in @($comparisonPairs | Where-Object { $failed -notcontains ([string]$_.NewPath) })) {
  $pairJson = [ordered]@{
    newPath = [string]$pair.NewPath
    oldPath = [string]$pair.OldPath
    label = [string]$pair.Label
  } | ConvertTo-Json -Compress
  Write-Host "PROGRESS: DWG_COMPARE_PAIR: $pairJson"
}

if (-not [string]::IsNullOrWhiteSpace($outputFolder)) {
  Write-Host "PROGRESS: OUTPUT_FOLDER: $outputFolder"
}
