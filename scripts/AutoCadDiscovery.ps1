# Shared by the CAD scripts, which all dot-source this file.
#
# Find-AcadCoreConsole finds installed AutoCAD Core Consoles (accoreconsole.exe). It is the
# scripts' fallback when the app did not pass -AcadCore; keep it in step with
# discover_autocad_installs() in main.py, which fills the app's AutoCAD picker.
#
# Autodesk records every install folder under HKLM\SOFTWARE\Autodesk\AutoCAD, so this
# finds AutoCAD on any drive and any future release. The Program Files scan covers
# installs whose registry entries are missing.

# Prints the end of what AutoCAD wrote during a failed run, one "ACAD_OUTPUT[label]: ..."
# line each. The app keeps these lines in its log and shows the last one with the error,
# so a failure on someone else's PC can be read without collecting files from it.
# -Lines takes output already in memory; -Paths takes the redirected output files.
function Write-AcadOutputTail {
  param(
    [string]$Label = "",
    [object[]]$Lines = @(),
    [string[]]$Paths = @(),
    [int]$Count = 12
  )

  $all = New-Object 'System.Collections.Generic.List[string]'
  foreach ($line in $Lines) {
    if ($null -ne $line) { $all.Add("$line") }
  }
  foreach ($path in $Paths) {
    if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { continue }
    foreach ($line in @(Get-Content -LiteralPath $path -ErrorAction SilentlyContinue)) {
      if ($null -ne $line) { $all.Add("$line") }
    }
  }

  # The Core Console writes UTF-16, which arrives here with a NUL after every character,
  # and it redraws its prompt with backspaces.
  $clean = @(
    $all |
      ForEach-Object { ($_ -replace '[\x00-\x08\x0B-\x1F]', '').Trim() } |
      Where-Object { $_ }
  )
  if ($clean.Count -eq 0) {
    Write-Host "ACAD_OUTPUT[$Label]: (AutoCAD wrote no output)"
    return
  }
  foreach ($line in @($clean | Select-Object -Last $Count)) {
    if ($line.Length -gt 300) { $line = $line.Substring(0, 300) }
    Write-Host "ACAD_OUTPUT[$Label]: $line"
  }
}

function Find-AcadCoreConsole {
  param(
    [string[]]$ProgramFilesRoots = @($env:ProgramW6432, $env:ProgramFiles),
    [switch]$SkipRegistry,
    # The oldest release the CAD scripts still support.
    [int]$MinYear = 2020
  )

  $candidates = @()

  if (-not $SkipRegistry) {
    $registryRoot = 'HKLM:\SOFTWARE\Autodesk\AutoCAD'
    if (Test-Path -LiteralPath $registryRoot) {
      foreach ($release in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
        foreach ($product in @(Get-ChildItem -LiteralPath $release.PSPath -ErrorAction SilentlyContinue)) {
          $properties = Get-ItemProperty -LiteralPath $product.PSPath -ErrorAction SilentlyContinue
          if ($properties -and $properties.AcadLocation) {
            $candidates += [pscustomobject]@{
              Folder = ([string]$properties.AcadLocation).Trim()
              Name   = [string]$properties.ProductName
            }
          }
        }
      }
    }
  }

  foreach ($root in $ProgramFilesRoots) {
    if ([string]::IsNullOrWhiteSpace($root)) { continue }
    $autodeskDir = Join-Path $root 'Autodesk'
    if (-not (Test-Path -LiteralPath $autodeskDir)) { continue }
    foreach ($dir in @(Get-ChildItem -LiteralPath $autodeskDir -Directory -Filter 'AutoCAD 20*' -ErrorAction SilentlyContinue)) {
      $candidates += [pscustomobject]@{ Folder = $dir.FullName; Name = $dir.Name }
    }
  }

  $found = @{}
  foreach ($candidate in $candidates) {
    if ([string]::IsNullOrWhiteSpace($candidate.Folder)) { continue }
    $exe = Join-Path $candidate.Folder 'accoreconsole.exe'
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { continue }
    $exe = [System.IO.Path]::GetFullPath($exe)

    # The folder name ("AutoCAD 2025") is the most reliable label; the registry
    # product name ("AutoCAD 2025 - English") covers renamed folders.
    $year = 0
    foreach ($text in @((Split-Path -Leaf $candidate.Folder.TrimEnd('\', '/')), $candidate.Name)) {
      if ($text -match 'AutoCAD\s+(\d{4})(?!\d)') { $year = [int]$Matches[1]; break }
    }
    if ($year -and $year -lt $MinYear) { continue }

    $key = $exe.ToLowerInvariant()
    if (-not $found.ContainsKey($key)) {
      $found[$key] = [pscustomobject]@{ Year = $year; Path = $exe }
    }
  }

  # Newest release first; installs whose year could not be read sort last.
  return @($found.Values | Sort-Object -Property @{ Expression = 'Year'; Descending = $true }, 'Path')
}
