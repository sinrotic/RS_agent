import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from two_tower_runtime import Handler, MODEL_KEY


class RuntimeHttpTest(unittest.TestCase):
    def setUp(self):
        class FakeRuntime:
            def infer(self, history):
                return {'embedding': [1.] + [0.] * 63, 'matched_history_count': len(history)}
        class TestHandler(Handler):
            runtime = FakeRuntime()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def test_java_style_chunked_request_is_supported(self):
        conn = http.client.HTTPConnection(*self.server.server_address)
        body = json.dumps({'model_key': MODEL_KEY, 'history_item_ids': ['item-a', 'item-b']}).encode()
        conn.request('POST', '/internal/model/two-tower/user-embedding', body=iter([body[:20], body[20:]]),
                     headers={'Content-Type': 'application/json'}, encode_chunked=True)
        response = conn.getresponse()
        self.assertEqual(200, response.status)
        self.assertEqual(64, len(json.loads(response.read())['embedding']))
        conn.close()

    def test_wrong_model_is_rejected(self):
        conn = http.client.HTTPConnection(*self.server.server_address)
        conn.request('POST', '/internal/model/two-tower/user-embedding',
                     body=json.dumps({'model_key': 'bge-m3', 'history_item_ids': ['item']}))
        self.assertEqual(400, conn.getresponse().status)
        conn.close()


if __name__ == '__main__':
    unittest.main()
