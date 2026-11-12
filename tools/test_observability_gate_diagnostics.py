import unittest
import socket
import threading
from unittest.mock import patch

import check_observability
from observability import probes


class GateDiagnosticsTest(unittest.TestCase):
    def test_failure_reports_stage_without_subprocess_details(self):
        with patch.object(check_observability, 'command', side_effect=ValueError('private-marker')):
            with patch.object(check_observability.subprocess, 'run'):
                with self.assertRaises(RuntimeError) as raised:
                    check_observability.smoke('botapi', 'observer')
        self.assertEqual('network', str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_framed_response_does_not_wait_for_keep_alive_close(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        release = threading.Event()
        def serve():
            with listener, listener.accept()[0] as connection:
                connection.recv(4096)
                connection.sendall(b'HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n'
                                   b'Connection: keep-alive\r\n\r\n{}')
                release.wait(5)
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            result = probes.request('127.0.0.1', listener.getsockname()[1])
            self.assertEqual((404, b'{}'), (result[0], result[2]))
        finally:
            release.set()
            thread.join(5)


if __name__ == '__main__':
    unittest.main()
