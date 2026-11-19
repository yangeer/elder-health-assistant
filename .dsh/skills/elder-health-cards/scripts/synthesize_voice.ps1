param(
    [Parameter(Mandatory = $true)][string]$InputText,
    [Parameter(Mandatory = $true)][string]$OutputWav
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$inputPath = (Resolve-Path -LiteralPath $InputText).Path
$lines = [System.IO.File]::ReadAllLines($inputPath, [System.Text.Encoding]::UTF8)
# A leading metadata line is for readers only.
if ($lines.Count -gt 0 -and $lines[0].StartsWith('【')) {
    $lines = @($lines | Select-Object -Skip 1)
}
$spoken = ($lines -join ' ').Trim()
if (-not $spoken) { throw 'The input has no spoken text.' }

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$stream = New-Object System.IO.MemoryStream
$reader = $null
try {
    $voice = $synth.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN'
    } | Select-Object -First 1
    if (-not $voice) { throw 'Install a zh-CN Windows desktop speech voice first.' }
    $synth.SelectVoice($voice.VoiceInfo.Name)
    $synth.Rate = -2
    $synth.SetOutputToWaveStream($stream)
    $synth.Speak($spoken)
    $synth.SetOutputToNull()

    $stream.Position = 12
    $reader = New-Object System.IO.BinaryReader($stream)
    $bytesPerSecond = 0
    $audioBytes = 0
    while ($stream.Position + 8 -le $stream.Length) {
        $chunk = [System.Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
        $size = $reader.ReadUInt32()
        $start = $stream.Position
        if ($chunk -eq 'fmt ' -and $size -ge 16) {
            $stream.Position = $start + 8
            $bytesPerSecond = $reader.ReadUInt32()
        } elseif ($chunk -eq 'data') {
            $audioBytes = $size
        }
        $stream.Position = $start + $size + ($size % 2)
    }
    if (-not $audioBytes -or -not $bytesPerSecond) { throw 'No valid PCM audio was produced.' }
    $seconds = $audioBytes / $bytesPerSecond
    if ($seconds -gt 60) {
        throw ('Audio is {0:F2}s. Shorten nonessential text and synthesize again.' -f $seconds)
    }
    $outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputWav)
    [System.IO.File]::WriteAllBytes($outputPath, $stream.ToArray())
    Write-Output ('Voice: {0}; duration: {1:F2}s' -f $voice.VoiceInfo.Name, $seconds)
} finally {
    $synth.Dispose()
    if ($reader) { $reader.Dispose() }
    $stream.Dispose()
}
