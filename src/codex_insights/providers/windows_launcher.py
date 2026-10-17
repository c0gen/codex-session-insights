"""ASCII-only outer command; Windows argument quoting is handled after launch."""
import base64
import subprocess


def quote(value):
    return "'" + value.replace("'", "''") + "'"


def command(arguments):
    # The provider's shell sees no paths or nested quotes. ProcessStartInfo
    # launches the bridge directly, forwarding its original stdin and stdout.
    script = f"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$p = New-Object System.Diagnostics.Process
$p.StartInfo.FileName = {quote(arguments[0])}
$p.StartInfo.Arguments = {quote(subprocess.list2cmdline(arguments[1:]))}
$p.StartInfo.UseShellExecute = $false
$p.StartInfo.CreateNoWindow = $true
$p.StartInfo.RedirectStandardInput = $true
$p.StartInfo.RedirectStandardOutput = $true
$p.StartInfo.RedirectStandardError = $true
$p.StartInfo.StandardOutputEncoding = New-Object System.Text.UTF8Encoding($false)
$p.StartInfo.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
$null = $p.Start()
$output = $p.StandardOutput.ReadToEndAsync()
$errors = $p.StandardError.ReadToEndAsync()
try {{
  $buffer = New-Object char[] 1048577
  $count = 0
  while ($count -lt $buffer.Length) {{
    $read = [Console]::In.Read($buffer, $count, $buffer.Length - $count)
    if ($read -eq 0) {{ break }}
    $count += $read
  }}
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($buffer, 0, $count)
  try {{ $p.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length) }} catch {{ }}
  try {{ $p.StandardInput.Close() }} catch {{ }}
  if (-not $p.WaitForExit(4000)) {{ $p.Kill(); exit 0 }}
  [Console]::Out.Write($output.Result)
  exit $p.ExitCode
}} finally {{
  if (-not $p.HasExited) {{ $p.Kill() }}
  $p.Dispose()
}}
"""
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return 'powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand ' + encoded
