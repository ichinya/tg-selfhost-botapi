import os
from pathlib import Path
import platform
import tempfile
import unittest
from unittest.mock import patch
from tools import file_access as access
from tools.file_contract import ContractError, read_private_file


class PathTests(unittest.TestCase):
    def test_ambiguous_paths_are_rejected_without_normalizing(self):
        for value in ('', '/', 'relative', '/a//b', '/a/../b', '/a/./b', '/a/', '/a\x00', '/a\\b'):
            with self.subTest(value=value), self.assertRaises(access.FileAccessError):
                access.absolute_path(value)
        self.assertEqual(str(access.absolute_path('/media/literal%2e.bin')), '/media/literal%2e.bin')
        self.assertFalse(access.overlaps('/media/bot', '/media/bot-other'))
        self.assertTrue(access.overlaps('/media', '/media/bot'))

    def test_unknown_platform_has_no_fallback(self):
        with patch.object(access.platform, 'system', return_value='Windows'):
            with self.assertRaises(access.UnsupportedPlatform):
                access.Root('/media/bot')
        with patch('tools.file_contract.os.name', 'nt'):
            with self.assertRaises(access.UnsupportedPlatform): read_private_file('/secret/token')


@unittest.skipUnless(platform.system() == 'Linux' and platform.machine() == 'x86_64',
                     'requires the mandatory Linux/amd64 gate')
class KernelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'bot'
        self.root.mkdir()
        self.file = self.root / 'fixture.bin'
        self.file.write_bytes(b'EXACT_SYNTHETIC_BYTES')
        self.outside = self.base / 'outside'
        self.outside.write_bytes(b'PRIVATE_CANARY')

    def test_private_secret_uses_same_fd_and_rejects_public_modes_and_links(self):
        self.file.chmod(0o640)
        data, info = read_private_file(str(self.file))
        self.assertEqual(data, b'EXACT_SYNTHETIC_BYTES')
        self.assertEqual(info.st_ino, self.file.stat().st_ino)
        for mode in (0o644, 0o650, 0o660, 0o740):
            self.file.chmod(mode)
            with self.subTest(mode=mode), self.assertRaises(ContractError):
                read_private_file(str(self.file))
        self.file.chmod(0o640)
        os.link(self.file, self.root / 'secret-hardlink')
        with self.assertRaises(access.FileAccessError):
            read_private_file(str(self.file))

    def test_fd_survives_unlink_without_reopening(self):
        with access.Root(str(self.root)) as root:
            fd, info = root.open(str(self.file))
            try:
                self.file.unlink()
                self.file.symlink_to(self.outside)
                self.assertEqual(os.read(fd, info.st_size), b'EXACT_SYNTHETIC_BYTES')
            finally:
                os.close(fd)

    def test_symlinks_hardlinks_fifo_and_foreign_root_fail(self):
        (self.root / 'leaf').symlink_to(self.outside)
        (self.root / 'parent').symlink_to(self.base, target_is_directory=True)
        os.link(self.outside, self.root / 'hardlink')
        os.mkfifo(self.root / 'fifo')
        with access.Root(str(self.root)) as root:
            for path in ('leaf', 'parent/outside', 'hardlink', 'fifo', 'missing', '.'):
                with self.subTest(path=path), self.assertRaises(access.FileAccessError):
                    root.open(str(self.root / path))
            with self.assertRaises(access.FileAccessError):
                root.open(str(self.outside))
        (self.base / 'root-link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(access.FileAccessError):
            access.Root(str(self.base / 'root-link'))

    def test_swap_between_validation_and_atomic_open_is_denied(self):
        original = access.openat2
        with access.Root(str(self.root)) as root:
            def swap(directory, path, flags, resolve):
                self.file.unlink()
                self.file.symlink_to(self.outside)
                return original(directory, path, flags, resolve)
            with patch.object(access, 'openat2', side_effect=swap):
                with self.assertRaises(access.FileAccessError):
                    root.open(str(self.file))

    def test_forbidden_inode_and_capability_failure(self):
        info = self.file.stat()
        with access.Root(str(self.root), [(info.st_dev, info.st_ino)]) as root:
            with self.assertRaises(access.FileAccessError):
                root.open(str(self.file))
        with patch.object(access, 'openat2', side_effect=access.UnsupportedPlatform('unavailable')):
            with self.assertRaises(access.UnsupportedPlatform):
                access.Root(str(self.root))

    def test_parent_swap_and_root_rename_never_read_outside(self):
        child = self.root / 'child'
        child.mkdir()
        (child / 'fixture').write_bytes(b'OWN_BYTES')
        outside = self.base / 'foreign'
        outside.mkdir()
        (outside / 'fixture').write_bytes(b'PRIVATE_CANARY')
        (outside / 'fixture.bin').write_bytes(b'PRIVATE_CANARY')
        original = access.openat2
        with access.Root(str(self.root)) as root:
            def swap_parent(directory, path, flags, resolve):
                child.rename(self.root / 'old-child')
                child.symlink_to(outside, target_is_directory=True)
                return original(directory, path, flags, resolve)
            with patch.object(access, 'openat2', side_effect=swap_parent):
                with self.assertRaises(access.FileAccessError):
                    root.open(str(child / 'fixture'))
            old_root = self.base / 'old-root'
            self.root.rename(old_root)
            self.root.symlink_to(outside, target_is_directory=True)
            fd, _ = root.open(str(self.file))
            try:
                self.assertEqual(os.read(fd, 1024), b'EXACT_SYNTHETIC_BYTES')
            finally:
                os.close(fd)


if __name__ == '__main__':
    unittest.main()
