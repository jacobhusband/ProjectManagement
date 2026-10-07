param(
  [Parameter(Mandatory = $true)][string]$AcadCore,
  [Parameter(Mandatory = $true)][string]$FilesListPath
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $AcadCore)) {
  Write-Host "PROGRESS: ERROR: AutoCAD Core Console not found at $AcadCore"
  exit 1
}

if (-not (Test-Path -LiteralPath $FilesListPath)) {
  Write-Host "PROGRESS: ERROR: Files list not found at $FilesListPath"
  exit 1
}

$dwgFiles = @(
  Get-Content -Path $FilesListPath -Encoding UTF8 |
    ForEach-Object { $_.ToString().Trim() } |
    Where-Object {
      $_ -and
      (Test-Path -LiteralPath $_) -and
      ([IO.Path]::GetExtension($_) -ieq ".dwg")
    } |
    ForEach-Object { [IO.Path]::GetFullPath($_) } |
    Select-Object -Unique
)

$tempRoot = Join-Path $env:TEMP ("acies-list-xrefs-" + [guid]::NewGuid().ToString("N"))
New-Item -Path $tempRoot -ItemType Directory -Force | Out-Null

try {
  $lispPath = Join-Path $tempRoot "list_xrefs.lsp"
  $scrPath = Join-Path $tempRoot "list_xrefs.scr"
  $lispPathForAcad = $lispPath -replace "\\", "/"

  $lisp = @'
(defun c:LISTXREFS (/ outPath out blk flags name refPath)
  (setq outPath (getenv "ACIES_XREF_OUT"))
  (if outPath
    (progn
      (setq out (open outPath "a"))
      (setq blk (tblnext "BLOCK" T))
      (while blk
        (setq flags (cdr (assoc 70 blk)))
        (setq name (cdr (assoc 2 blk)))
        (setq refPath (cdr (assoc 1 blk)))
        (if (and flags name refPath (/= refPath "") (/= 0 (logand flags 12)))
          (write-line (strcat name "\t" refPath) out)
        )
        (setq blk (tblnext "BLOCK"))
      )
      (close out)
    )
  )
  (princ)
)
'@
  Set-Content -Path $lispPath -Value $lisp -Encoding ASCII

  # Scripts already use command-line file prompts. Leave registry-backed FILEDIA alone.
  $scriptLines = @(
    "CMDECHO 0",
    "(load `"$lispPathForAcad`")",
    "LISTXREFS",
    "QUIT"
  )
  Set-Content -Path $scrPath -Value ($scriptLines -join "`r`n") -Encoding ASCII

  $results = @()
  foreach ($dwg in $dwgFiles) {
    $outPath = Join-Path $tempRoot (([guid]::NewGuid().ToString("N")) + ".txt")
    $env:ACIES_XREF_OUT = $outPath
    Write-Host "PROGRESS: Reading XREFs from $([IO.Path]::GetFileName($dwg))"
    & $AcadCore /i "$dwg" /s "$scrPath" 2>&1 | Out-Null

    $refs = @()
    if (Test-Path -LiteralPath $outPath) {
      $refs = @(
        Get-Content -Path $outPath -Encoding UTF8 |
          ForEach-Object {
            $line = $_.ToString()
            if (-not $line.Trim()) { return }
            $parts = $line -split "`t", 2
            $name = $parts[0].Trim()
            $refPath = if ($parts.Count -gt 1) { $parts[1].Trim() } else { "" }
            $fileName = if ($refPath) { [IO.Path]::GetFileName($refPath) } else { "" }
            $baseName = if ($fileName) { [IO.Path]::GetFileNameWithoutExtension($fileName) } else { $name }
            [pscustomobject]@{
              name = $name
              path = $refPath
              fileName = $fileName
              baseName = $baseName
            }
          }
      )
    }

    $results += [pscustomobject]@{
      sourceDwg = $dwg
      references = $refs
    }
  }

  $json = $results | ConvertTo-Json -Depth 8 -Compress
  Write-Host "XREF_JSON:$json"
}
finally {
  Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
  Remove-Item Env:\ACIES_XREF_OUT -ErrorAction SilentlyContinue
}
