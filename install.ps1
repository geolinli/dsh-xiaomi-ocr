<#
.SYNOPSIS
  Install the local Xiaomi-OCR-0 MCP plugin for DeepSeek Harness.

.DESCRIPTION
  Creates .venv, installs the verified torch/transformers stack, downloads the
  0.8B weights (~1.7 GB) from an HF mirror, and renders plugin/cordis.patch.yml
  with absolute paths for this machine.

.EXAMPLE
  .\install.ps1
  .\install.ps1 -Cpu
  .\install.ps1 -SkipModel -ModelMirror https://hf-mirror.com
  .\install.ps1 -RenderOnly
#>
[CmdletBinding()]
param(
    [switch]$Cpu,
    [switch]$SkipModel,
    [switch]$RenderOnly,
    [string]$ModelMirror = "https://hf-mirror.com",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$VenvPy = Join-Path $Venv "Scripts\python.exe"
$Tmp = Join-Path $Root "tmp"
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
$env:TMP = $Tmp
$env:TEMP = $Tmp

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function OkMsg($m) { Write-Host "    $m" -ForegroundColor Green }
function WarnMsg($m) { Write-Host "    ! $m" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 1. python
Step "Locating Python 3.10+"
if (-not $Python) {
    foreach ($cand in @("python", "python3", "py")) {
        $cmd = Get-Command $cand -ErrorAction SilentlyContinue
        if ($cmd) { $Python = $cmd.Source; break }
    }
}
if (-not $Python) { throw "Python 3.10+ not found. Install from https://www.python.org/downloads/ and rerun." }

$ver = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
$parts = $ver -split '\.'
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    throw "Python $ver is too old; 3.10+ required (3.13 recommended)."
}
OkMsg "Python $ver at $Python"

if ($RenderOnly) {
    Step "Render-only mode: writing plugin/cordis.patch.yml"
    if (-not (Test-Path $VenvPy)) { WarnMsg "venv missing; paths will point at a venv that does not exist yet" }
} else {
    # ------------------------------------------------------------ 2. venv
    Step "Creating .venv"
    if (-not (Test-Path $VenvPy)) {
        & $Python -m venv $Venv
        if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
    }
    OkMsg $Venv

    Step "Installing Python dependencies (this downloads ~2-3 GB on first run)"
    & $VenvPy -m pip install --upgrade pip --quiet

    if ($Cpu) {
        & $VenvPy -m pip install "torch==2.14.0" "torchvision==0.29.0"
    } else {
        OkMsg "installing CUDA build from download.pytorch.org/whl/cu130"
        & $VenvPy -m pip install --index-url https://download.pytorch.org/whl/cu130 "torch==2.14.0+cu130" "torchvision==0.29.0+cu130"
        if ($LASTEXITCODE -ne 0) {
            WarnMsg "CUDA wheels unavailable; falling back to CPU torch (pass -Cpu to silence this)"
            & $VenvPy -m pip install "torch==2.14.0" "torchvision==0.29.0"
        }
    }
    & $VenvPy -m pip install "transformers==5.17.0" pillow accelerate mcp pypdfium2
    if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
    OkMsg "dependencies installed"

    # ------------------------------------------------------------ 3. model
    if (-not $SkipModel) {
        Step "Downloading Xiaomi-OCR-0 weights (~1.7 GB) from $ModelMirror"
        $env:HF_ENDPOINT = $ModelMirror
        & $VenvPy (Join-Path $Root "fetch_model.py")
        if ($LASTEXITCODE -ne 0) { throw "model download failed; rerun with -SkipModel after placing model/ manually" }
    } else {
        WarnMsg "skipped model download (-SkipModel)"
    }
}

# ---------------------------------------------------------------- 4. render
Step "Rendering plugin/cordis.patch.yml"
$tpl = Get-Content (Join-Path $Root "plugin\cordis.patch.yml.template") -Raw -Encoding UTF8
$rendered = $tpl.Replace("{{PYTHON}}", $VenvPy).Replace("{{SERVER}}", (Join-Path $Root "mcp_server.py")).Replace("{{ROOT}}", $Root)
if ($Cpu) { $rendered = $rendered.Replace("XIAOMI_OCR_DEVICE: cuda", "XIAOMI_OCR_DEVICE: cpu") }
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $Root "plugin\cordis.patch.yml"), $rendered, $utf8NoBom)
OkMsg (Join-Path $Root "plugin\cordis.patch.yml")

Write-Host @"

============================================================
Next steps
============================================================
1) Restart DeepSeek Harness.
2) Sidebar -> Plugins -> "Add plugin".
3) Paste THIS path (it is the plugin subdirectory, not the repo root):

   PASTE THIS PLUGIN DIRECTORY INTO HARNESS (Plugins -> Add plugin):
       $Root\plugin

   That directory contains package.json and cordis.patch.yml.
4) Click Install. The card "Local OCR (Xiaomi-OCR-0)" appears, switched on.
   Tools: mcp__xiaomi_ocr__ocr_image / ocr_text / kie_image / vqa_image /
          ocr_batch / ocr_pdf / model_status / model_release

Optional smoke test before wiring Harness (loads the model once):

   & "$VenvPy" "$Root\smoke_test.py"

Uninstall: remove the plugin in Plugins, then delete this directory.
"@ -ForegroundColor Gray
