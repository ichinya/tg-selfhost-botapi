"""The replacement CLI rejects positional credentials without touching the network."""
import contextlib
import io
import unittest
from unittest import mock
from migration_cli import main

class ConfigTests(unittest.TestCase):
    def test_old_positional_token_rejected_without_network_or_echo(self):
        with mock.patch('migration_cli.Client') as client, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['123:synthetic', 'http://localhost']), 4)
            client.assert_not_called()
            self.assertNotIn('123:synthetic', out.getvalue())
