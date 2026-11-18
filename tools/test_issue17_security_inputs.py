import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import warnings
import getpass
import subprocess
from migration_cli import private_text, parser, runtime


@unittest.skipUnless(os.name == 'posix', 'POSIX protected inputs')
class ProtectedInputs(unittest.TestCase):
    def test_token_file_normalization_is_one_line_only(self):
        args=parser().parse_args(['plan','--operation','safe','--action','polling'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'token';path.touch(mode=0o600)
            env={'OLD_BOT_URL':'https://api.telegram.org','SELF_BOT_URL':'https://target.example','BOT_TOKEN_FILE':str(path)}
            for suffix in ('','\n','\r\n'):
                path.write_bytes(('123:synthetic_marker'+suffix).encode())
                self.assertEqual(runtime(args,env).token,'123:synthetic_marker')
            for value in ('','123:synthetic_marker\r','123:synthetic_marker\n\n','123:synthetic\x00_marker',' 123:synthetic_marker'):
                path.write_bytes(value.encode())
                with self.assertRaises(ValueError):runtime(args,env)

    def test_snapshot_permissions_links_and_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'token'
            path.write_text('123:synthetic_marker\r\n')
            path.chmod(0o600)
            self.assertEqual(private_text(path), '123:synthetic_marker\r\n')
            path.chmod(0o644)
            with self.assertRaises(ValueError): private_text(path)

    def test_canonical_bash_snapshots_and_rejects_links(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input';output=Path(directory)/'snapshot'
            path.write_text('synthetic-private');path.chmod(0o600)
            command=['bash','-c','source "$1"; WP_SCRIPT_DIR=$2; wp_private_file "$3" "$4"',
                     '_',str(root/'tools/webhook_profile_runtime.sh'),str(root),str(path),str(output)]
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,'protected snapshot failed')
            self.assertEqual(output.read_text(),'synthetic-private')
            self.assertNotIn('synthetic-private',result.stdout+result.stderr)
            path.chmod(0o644)
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn(str(path),result.stdout+result.stderr)
            path.chmod(0o600)
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError): private_text(link)
            link.unlink()
            os.link(path, link)
            with self.assertRaises(ValueError): private_text(path)


class HiddenInputs(unittest.TestCase):
    def test_echo_fallback_fails_closed(self):
        args = parser().parse_args(['plan', '--operation', 'safe', '--action', 'polling'])
        env = {'OLD_BOT_URL':'https://api.telegram.org', 'SELF_BOT_URL':'https://target.example'}
        def fallback(*args):
            warnings.warn('fallback', getpass.GetPassWarning)
            return '123:must_not_be_read'
        with mock.patch('sys.stdin.isatty', return_value=True), mock.patch('getpass.getpass', side_effect=fallback):
            with self.assertRaisesRegex(ValueError, 'hidden token input unavailable'):
                runtime(args, env)
