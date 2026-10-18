"""不需要 Docker daemon 的部署契约检查。"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

DIRECTORY = Path(__file__).resolve().parent


class OperationsContracts(unittest.TestCase):
    def test_notification_configuration_serializes_secret_and_rejects_unsafe_url(self):
        spec = importlib.util.spec_from_file_location('configure_alerts', DIRECTORY.parents[1] / 'remote/ops/configure_alerts.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        url = 'https://receiver.example/alerts?key=private%22value'
        rendered = json.loads(module.render(url))
        self.assertEqual(rendered['receivers'][0]['webhook_configs'][0]['url'], url)
        for bad in ('', 'http://receiver.example', 'https://user:secret@example.com', 'https://example.com/#fragment'):
            with self.assertRaises(ValueError): module.render(bad)

    def test_every_new_authoritative_commerce_table_is_in_backup_scope(self):
        schema = (DIRECTORY.parents[2] / 'sql/rs_service_commerce_v1_schema.sql').read_text(encoding='utf-8')
        backup = (DIRECTORY.parents[1] / 'remote/app/backup_application_state.sh').read_text(encoding='utf-8')
        pattern = re.search(r'grep -E "(.*?)"', backup).group(1)
        tables = re.findall(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)', schema)
        self.assertGreater(len(tables), 20)
        for table in tables: self.assertIsNotNone(re.match(pattern, table), table)
        self.assertIsNone(re.match(pattern, 'amazon_reviews_base'))

    def test_isolated_compose_limits_memory_and_uses_three_brokers(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = dict(os.environ, RS_IT_JAR_DIR=temporary, RS_IT_OUTPUT_DIR=temporary,
                       **{key: 'test-'+'x'*32 for key in ('RS_IT_DB_PASSWORD','RS_COMMERCE_OPS_READ_TOKEN','RS_COMMERCE_OPS_WRITE_TOKEN','RS_COMMERCE_SERVICE_TOKEN','RS_PAYMENT_MOCK_CALLBACK_SECRET')})
            result = subprocess.run(['docker','compose','-f',str(DIRECTORY/'fullstack.compose.yml'),'--profile','restore','--profile','notifications','config','--format','json'], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            services = json.loads(result.stdout)['services']
            self.assertLessEqual(sum(int(service['mem_limit']) for service in services.values()), 6 * 1024**3)
            for name, service in services.items():
                for port in service.get('ports', []): self.assertEqual(port['host_ip'], '127.0.0.1', name)
            for broker in ('kafka','kafka-2','kafka-3'):
                self.assertEqual(str(services[broker]['environment']['KAFKA_MIN_INSYNC_REPLICAS']), '2')
            self.assertEqual(str(services['kafka-init']['environment']['RS_COMMERCE_KAFKA_REPLICAS']), '3')


if __name__ == '__main__': unittest.main()
