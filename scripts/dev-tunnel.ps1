param(
    [string]$SshHost = "server",
    [switch]$InfraOnly
)

$ErrorActionPreference = "Stop"

$infraForwards = @(
    "13306:127.0.0.1:13306", # MySQL
    "16379:127.0.0.1:16379", # Redis
    "18848:127.0.0.1:18848", # Nacos API
    "18080:127.0.0.1:18080", # Nacos console
    "19848:127.0.0.1:19848", # Nacos gRPC
    "19849:127.0.0.1:19849", # Nacos raft
    "19200:127.0.0.1:19200", # Elasticsearch
    "19000:127.0.0.1:19000", # MinIO API
    "19001:127.0.0.1:19001", # MinIO console
    "19042:127.0.0.1:19042", # Cassandra CQL
    "19530:127.0.0.1:19530", # Milvus gRPC
    "19091:127.0.0.1:19091"  # Milvus metrics
)

$appForwards = @(
    "18088:127.0.0.1:18088", # Java API gateway
    "18101:127.0.0.1:18101", # Java user service
    "18102:127.0.0.1:18102", # Java catalog service
    "18103:127.0.0.1:18103", # Java recommend service
    "18104:127.0.0.1:18104", # Java agent service
    "18105:127.0.0.1:18105"  # Java model service
)

$forwards = @()
$forwards += $infraForwards
if (-not $InfraOnly) {
    $forwards += $appForwards
}

$sshArgs = @(
    "-N",
    "-o", "ExitOnForwardFailure=yes",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3"
)

foreach ($forward in $forwards) {
    $sshArgs += "-L"
    $sshArgs += $forward
}

$sshArgs += $SshHost

Write-Host "Starting SSH tunnel to $SshHost"
Write-Host "Forwarded ports:"
foreach ($forward in $forwards) {
    Write-Host "  127.0.0.1:$($forward.Split(':')[0]) -> $SshHost $($forward.Substring($forward.IndexOf(':') + 1))"
}
Write-Host ""
Write-Host "Keep this terminal open while developing. Press Ctrl+C to stop."

ssh @sshArgs
