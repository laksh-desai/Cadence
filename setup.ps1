<#
Cadence provisioning helper - automates docs/shipping.md section A (steps 4-8) for a
fresh Windows machine. Idempotent and NON-DESTRUCTIVE: safe to re-run, and it never
overwrites existing patient data/keys or an existing hf_config.yaml.

Run from the project root:
    powershell -ExecutionPolicy Bypass -File .\setup.ps1

It does NOT install Python or Ollama for you (those are deliberate, sometimes-admin
downloads) - it checks for them and tells you exactly what to get. It DOES: build the
venv, install dependencies, pull the models, set the HF token + speed env vars, create
the desktop shortcut, and run a quick verification. After it finishes, do the HIPAA
device hardening in docs\device-safeguards-checklist.md before any real patient data.
#>

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$py  = Join-Path $root '.venv\Scripts\python.exe'
$MODEL      = 'williamljx/medgemma-4b-it-Q4_K_M-GGUF'   # quality tier (docs/shipping.md)
$FAST_MODEL = 'gemma2:2b'                                # optional Fast-draft tier

function Section($t){ Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Ok($t){   Write-Host "  [ok] $t"  -ForegroundColor Green }
function Warn($t){ Write-Host "  [!]  $t"  -ForegroundColor Yellow }
function Fail($t){ Write-Host "  [x]  $t"  -ForegroundColor Red }

# --- 1. Python 3.12 -----------------------------------------------------------
Section 'Python'
if(-not (Get-Command python -ErrorAction SilentlyContinue)){
  Fail "Python not found on PATH. Install Python 3.12 from python.org (tick 'Add python.exe to PATH'), then re-run."
  exit 1
}
$ver = (& python --version) 2>&1
if("$ver" -notmatch '3\.12'){ Warn "Found $ver - Cadence pins wheels for 3.12; 3.12.x strongly recommended." }
else { Ok "$ver" }

# --- 2. venv + dependencies ---------------------------------------------------
Section 'Virtual environment + dependencies'
if(-not (Test-Path $py)){
  Write-Host '  creating .venv ...'
  & python -m venv (Join-Path $root '.venv')
}
& $py -m pip install --upgrade pip | Out-Null
Write-Host '  installing requirements (large: torch, transformers) ...'
& $py -m pip install -r (Join-Path $root 'requirements.txt')
& $py -c "import torch, transformers, librosa, fastapi; print('imports ok')"
Ok 'dependencies installed'

# --- 3. Ollama + models -------------------------------------------------------
Section 'Ollama + models'
if(-not (Get-Command ollama -ErrorAction SilentlyContinue)){
  Fail "Ollama not installed. Get it from https://ollama.com/download, then re-run."
  exit 1
}
Ok 'ollama present'
$have = (& ollama list) 2>&1 | Out-String
if("$have" -match 'medgemma'){ Ok 'MedGemma (quality) already pulled' }
else { Write-Host "  pulling $MODEL (several GB) ..."; & ollama pull $MODEL }
if("$have" -match 'gemma2:2b'){ Ok 'gemma2:2b (fast draft) already pulled' }
else {
  Write-Host "  pulling $FAST_MODEL (~1.6 GB, optional Fast-draft tier) ..."
  try { & ollama pull $FAST_MODEL } catch { Warn "fast-draft model pull failed (optional) - Quality tier still works." }
}

# --- 4. Transcription token (MedASR / Hugging Face) ---------------------------
Section 'Transcription (MedASR / Hugging Face token)'
$cfg     = Join-Path $root 'app\transcribe\hf_config.yaml'
$example = Join-Path $root 'app\transcribe\hf_config.example.yaml'
if(Test-Path $cfg){ Ok 'hf_config.yaml already present (left as-is)' }
else {
  $tok = Read-Host 'Paste the Hugging Face READ token (blank = set up later)'
  if($tok){
    (Get-Content $example) -replace 'hf_token:.*', "hf_token: `"$tok`"" | Set-Content -Encoding UTF8 $cfg
    Ok 'hf_config.yaml written'
  } else {
    Warn 'skipped - create app\transcribe\hf_config.yaml before using the mic (docs\medasr-setup.md)'
  }
}

# --- 5. Performance tuning (this session's Ollama config) ---------------------
Section 'Performance tuning (Ollama)'
[Environment]::SetEnvironmentVariable('OLLAMA_FLASH_ATTENTION','1','User')
[Environment]::SetEnvironmentVariable('OLLAMA_KV_CACHE_TYPE','q8_0','User')
Ok 'OLLAMA_FLASH_ATTENTION=1, OLLAMA_KV_CACHE_TYPE=q8_0 set (restart Ollama to apply)'
Warn 'Restart Ollama now (quit the tray app and reopen) so the settings above take effect.'

# --- 6. Desktop shortcut ------------------------------------------------------
Section 'Desktop shortcut'
$pyw      = Join-Path $root '.venv\Scripts\pythonw.exe'
$launcher = Join-Path $root 'launcher.py'
$lnk      = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Cadence.lnk'
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath       = $pyw
$sc.Arguments        = "`"$launcher`""
$sc.WorkingDirectory = $root
$sc.Description       = 'Cadence - local clinical note generator'
$sc.Save()
Ok "shortcut created: $lnk"

# --- 7. Quick verification ----------------------------------------------------
Section 'Verification'
try { & $py (Join-Path $root 'scripts\verify_pipeline.py') } catch { Warn "verify_pipeline reported an issue: $_" }

Write-Host "`nSetup complete." -ForegroundColor Cyan
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Restart Ollama (for the perf settings)."
Write-Host "  2. Launch Cadence from the desktop shortcut; confirm the System Status page is green."
Write-Host "  3. Deeper checks (slower):"
Write-Host "       $py scripts\verify_transcription.py"
Write-Host "       $py scripts\validate_quality.py"
Write-Host "  4. HIPAA device hardening: docs\device-safeguards-checklist.md (BitLocker + lock screen)."
Write-Host "  5. Set up the backup routine: python scripts\backup.py backup --dest <USB drive>"
