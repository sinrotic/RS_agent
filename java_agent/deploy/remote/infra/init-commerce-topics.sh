#!/usr/bin/env bash
set -euo pipefail

partitions="${RS_COMMERCE_KAFKA_PARTITIONS:-3}"
replicas="${RS_COMMERCE_KAFKA_REPLICAS:-1}"
bootstrap="${RS_KAFKA_BOOTSTRAP_SERVERS:-kafka:9092}"
[[ "$partitions" =~ ^[1-9][0-9]*$ && "$replicas" =~ ^[1-9][0-9]*$ ]] || { echo 'Kafka 分区/副本参数不合法' >&2; exit 1; }
for topic in checkout-seckill-accepted checkout-seckill-accepted.DLT; do
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server "$bootstrap" --create --if-not-exists \
    --topic "$topic" --partitions "$partitions" --replication-factor "$replicas"
  description="$(/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$bootstrap" --describe --topic "$topic")"
  [[ "$description" =~ PartitionCount:[[:space:]]*([0-9]+) ]] || { echo "无法读取 $topic 分区数" >&2; exit 1; }
  [[ "${BASH_REMATCH[1]}" == "$partitions" ]] || { echo "$topic 分区数与配置不符，请先人工核对，未修改既有 topic" >&2; exit 1; }
  [[ "$description" =~ ReplicationFactor:[[:space:]]*([0-9]+) ]] || { echo "无法读取 $topic 副本数" >&2; exit 1; }
  [[ "${BASH_REMATCH[1]}" == "$replicas" ]] || { echo "$topic 副本数与配置不符，请先人工核对" >&2; exit 1; }
done
echo '秒杀业务与死信 topic 初始化及配置检查完成'
