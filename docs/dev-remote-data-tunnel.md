# Remote Data Tunnel for Local Development

This project can use remote data services from local development through an SSH tunnel. The tunnel keeps the remote databases bound to remote `127.0.0.1`, while exposing them on local ports only after the developer starts a local command.

## Service Ports

| Service | Local endpoint | Remote endpoint |
| --- | --- | --- |
| MySQL | `127.0.0.1:13306` | `127.0.0.1:13306` |
| Redis | `127.0.0.1:16379` | `127.0.0.1:16379` |
| Nacos | `127.0.0.1:18848` | `127.0.0.1:18848` |
| Elasticsearch | `127.0.0.1:19200` | `127.0.0.1:19200` |
| MinIO | `127.0.0.1:19000` | `127.0.0.1:19000` |
| Scylla | `127.0.0.1:19042` | `127.0.0.1:19042` |
| Milvus | `127.0.0.1:19530` | `127.0.0.1:19530` |

## Manual Tunnel

Run this only when local development needs the remote data services:

```powershell
ssh -N server `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  -L 13306:127.0.0.1:13306 `
  -L 16379:127.0.0.1:16379 `
  -L 18848:127.0.0.1:18848 `
  -L 19200:127.0.0.1:19200 `
  -L 19000:127.0.0.1:19000 `
  -L 19042:127.0.0.1:19042 `
  -L 19530:127.0.0.1:19530
```

Keep that terminal open while developing. Closing the terminal closes the tunnel.

## Auto-Start From Local Dev Commands

For a smoother workflow, put this helper in a local PowerShell profile or a project-local script such as `scripts/dev/start-remote-data-tunnel.ps1`.

```powershell
function Test-PortOpen {
  param(
    [string]$HostName = "127.0.0.1",
    [int]$Port
  )

  $client = New-Object Net.Sockets.TcpClient
  try {
    $iar = $client.BeginConnect($HostName, $Port, $null, $null)
    if (-not $iar.AsyncWaitHandle.WaitOne(300)) { return $false }
    $client.EndConnect($iar)
    return $true
  } catch {
    return $false
  } finally {
    $client.Close()
  }
}

function Ensure-RsRemoteDataTunnel {
  if (Test-PortOpen -Port 13306) {
    Write-Host "Remote data tunnel already available on 127.0.0.1:13306"
    return
  }

  Start-Process ssh -WindowStyle Hidden -ArgumentList @(
    "-N",
    "server",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-L", "13306:127.0.0.1:13306",
    "-L", "16379:127.0.0.1:16379",
    "-L", "18848:127.0.0.1:18848",
    "-L", "19200:127.0.0.1:19200",
    "-L", "19000:127.0.0.1:19000",
    "-L", "19042:127.0.0.1:19042",
    "-L", "19530:127.0.0.1:19530"
  )

  for ($i = 0; $i -lt 20; $i++) {
    if (Test-PortOpen -Port 13306) {
      Write-Host "Remote data tunnel is ready."
      return
    }
    Start-Sleep -Milliseconds 500
  }

  throw "Remote data tunnel did not become ready on 127.0.0.1:13306"
}
```

Then call it before starting local services:

```powershell
Ensure-RsRemoteDataTunnel
mvn spring-boot:run
```

or:

```powershell
Ensure-RsRemoteDataTunnel
python -m your_local_entrypoint
```

## Recommended Local Config

Local code should point to local loopback endpoints. The SSH tunnel decides whether these endpoints reach remote data services.

```text
MYSQL_HOST=127.0.0.1
MYSQL_PORT=13306
REDIS_HOST=127.0.0.1
REDIS_PORT=16379
NACOS_ADDR=127.0.0.1:18848
ES_URL=http://127.0.0.1:19200
MINIO_ENDPOINT=http://127.0.0.1:19000
SCYLLA_HOST=127.0.0.1
SCYLLA_PORT=19042
MILVUS_HOST=127.0.0.1
MILVUS_PORT=19530
```

## Notes

- This is intended for local development, not production exposure.
- If a local port is already occupied, change only the local side, for example `-L 23306:127.0.0.1:13306`, and update local config to use `127.0.0.1:23306`.
- The SSH alias `server` must exist in the local SSH config.
- This approach does not expose databases to the public network.
