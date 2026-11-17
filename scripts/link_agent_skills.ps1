# Copy dup-agent-skills packs into this repo's .agents/skills for Cursor discovery.
param(
  [string]$SkillsRoot = ""
)
$ErrorActionPreference = "Stop"
$BotRoot = Split-Path -Parent $PSScriptRoot
if (-not $SkillsRoot) {
  $candidate = Join-Path (Split-Path $BotRoot) "dup-agent-skills"
  if (Test-Path (Join-Path $candidate "skills")) {
    $SkillsRoot = $candidate
  } else {
    $SkillsRoot = Join-Path $env:USERPROFILE "Desktop\dup-agent-skills"
  }
}
$Src = Join-Path $SkillsRoot "skills"
if (-not (Test-Path $Src)) {
  throw "missing skills at $Src — clone https://github.com/Gruver87/dup-agent-skills"
}
$Dst = Join-Path $BotRoot ".agents\skills"
New-Item -ItemType Directory -Path $Dst -Force | Out-Null
Get-ChildItem $Dst -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  Remove-Item $_.FullName -Recurse -Force
}
$n = 0
Get-ChildItem $Src -Directory | ForEach-Object {
  Copy-Item $_.FullName (Join-Path $Dst $_.Name) -Recurse -Force
  Write-Host "linked $($_.Name)"
  $n++
}
Write-Host "OK link_agent_skills n=$n -> $Dst"
Write-Host "Policy: see docs/PROTOCOL_STATUS.md — v1 stopped, SPOT_ENTRIES off"
exit 0
