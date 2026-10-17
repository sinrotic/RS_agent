param(
    [string]$SshHost = 'server',
    [int]$LocalPort = 18088
)
$ErrorActionPreference = 'Stop'
$previewUrl = "http://127.0.0.1:$LocalPort/"
try {
    $response = Invoke-WebRequest "${previewUrl}healthz" -TimeoutSec 2
    if ($response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'ok') {
        Write-Output "前端入口已可用：$previewUrl"
        return
    }
} catch { }
if (Get-NetTCPConnection -State Listen -LocalPort $LocalPort -ErrorAction SilentlyContinue) {
    throw "本机端口 $LocalPort 已被其他服务占用，请用 -LocalPort 指定空闲端口。"
}
$previewLog = Join-Path $env:TEMP "rs-frontend-tunnel-$LocalPort.log"
$process = Start-Process ssh -WindowStyle Hidden -PassThru -ArgumentList @(
    '-N', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
    '-L', "127.0.0.1:${LocalPort}:127.0.0.1:18089", $SshHost
) -RedirectStandardError $previewLog
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ($process.HasExited) { throw "SSH 隧道启动失败，请查看 $previewLog" }
    try {
        $response = Invoke-WebRequest "${previewUrl}healthz" -TimeoutSec 2
        if ($response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'ok') {
            Write-Output "前端入口：$previewUrl（SSH PID: $($process.Id)）"
            return
        }
    } catch { }
    Start-Sleep -Milliseconds 500
}
Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
throw "前端入口未就绪，请检查远端 18089 端口及 $previewLog"
