# RS Agent Java remote infra

This compose stack is for the remote `~/RS_agent_java` deployment.

It starts only the middleware needed by the Java services:

- Nacos
- MySQL
- Redis
- Elasticsearch
- MinIO

All host ports are bound to `127.0.0.1` on the remote server. Use SSH tunnels for local development access, and expose only the Java gateway through Cloudflare Tunnel later.

## Start

```bash
cd ~/RS_agent_java/infra
cp .env.example .env
docker compose --env-file .env up -d
docker compose --env-file .env ps
```

## Local SSH tunnels

```bash
ssh -N \
  -L 18848:127.0.0.1:18848 \
  -L 18080:127.0.0.1:18080 \
  -L 13306:127.0.0.1:13306 \
  -L 16379:127.0.0.1:16379 \
  -L 19200:127.0.0.1:19200 \
  -L 19000:127.0.0.1:19000 \
  -L 19001:127.0.0.1:19001 \
  server
```

Local Java development can then use:

- `NACOS_SERVER_ADDR=127.0.0.1:18848`
- Nacos console: `http://127.0.0.1:18080`
- `SPRING_DATASOURCE_URL=jdbc:mysql://127.0.0.1:13306/rs_agent`
- `SPRING_REDIS_HOST=127.0.0.1`
- `SPRING_REDIS_PORT=16379`
- `RS_ELASTICSEARCH_URI=http://127.0.0.1:19200`
- `RS_MINIO_ENDPOINT=http://127.0.0.1:19000`
