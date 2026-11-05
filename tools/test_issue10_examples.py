"""Execute both EN/RU published examples against loopback source/target/sink."""
from pathlib import Path
import subprocess
import unittest


class ExampleTests(unittest.TestCase):
    def test_bash_scenarios_and_published_examples(self):
        tools = Path(__file__).resolve().parent
        result = subprocess.run(['node', str(tools / 'issue10_timeout.cjs'), '300',
                                 'node', str(tools / 'test_issue10_bash.cjs')],
                                text=True, capture_output=True, timeout=320)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
