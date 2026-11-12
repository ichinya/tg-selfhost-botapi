"""Linux/amd64 FD-only file access. No realpath/open fallback is permitted."""
import ctypes
import errno
import os
import platform
import stat
from pathlib import PurePosixPath


class FileAccessError(Exception):
    """Public exception intentionally contains no pathname or OS diagnostics."""


class UnsupportedPlatform(FileAccessError):
    pass


def absolute_path(value):
    if not isinstance(value, str):
        raise FileAccessError('invalid path')
    try:
        size = len(value.encode('utf-8'))
    except UnicodeError:
        raise FileAccessError('invalid path') from None
    if (not value.startswith('/') or value == '/'
            or any(ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value or size > 4096
            or any(p in ('', '.', '..') for p in value.split('/')[1:])):
        raise FileAccessError('invalid path')
    return PurePosixPath(value)


def overlaps(first, second):
    a, b = absolute_path(first), absolute_path(second)
    return a == b or a in b.parents or b in a.parents


class OpenHow(ctypes.Structure):
    _fields_ = [('flags', ctypes.c_uint64), ('mode', ctypes.c_uint64), ('resolve', ctypes.c_uint64)]


NO_XDEV, NO_MAGICLINKS, NO_SYMLINKS, BENEATH = 0x01, 0x02, 0x04, 0x08


def openat2(directory, path, flags, resolve):
    if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
        raise UnsupportedPlatform('Linux/amd64 with openat2 is required')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    how = OpenHow(flags, 0, resolve)
    fd = libc.syscall(ctypes.c_long(437), ctypes.c_int(directory),
                      ctypes.c_char_p(os.fsencode(path)), ctypes.byref(how), ctypes.sizeof(how))
    if fd < 0:
        code = ctypes.get_errno()
        if code in (errno.ENOSYS, errno.EINVAL, errno.EPERM):
            raise UnsupportedPlatform('required openat2 policy unavailable')
        raise FileAccessError('file unavailable')
    return int(fd)


class Root:
    """Pin the root without following symlinks, then open children atomically."""
    def __init__(self, path, forbidden_inodes=()):
        self.path = absolute_path(path)
        self.fd = -1
        self.forbidden_inodes = frozenset(forbidden_inodes)
        if platform.system() != 'Linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
            raise UnsupportedPlatform('Linux/amd64 with openat2 is required')
        anchor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            # The root itself can be a bind mount; its ancestors may not be symlinks.
            self.fd = openat2(anchor, str(self.path)[1:], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
                              BENEATH | NO_SYMLINKS | NO_MAGICLINKS)
            try:
                probe = openat2(self.fd, '.', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC,
                                BENEATH | NO_SYMLINKS | NO_MAGICLINKS | NO_XDEV)
                os.close(probe)
            except BaseException:
                self.close()
                raise
        finally:
            os.close(anchor)

    def open(self, path):
        candidate = absolute_path(path)
        if self.fd < 0 or self.path not in candidate.parents:
            raise FileAccessError('file unavailable')
        relative = str(candidate.relative_to(self.path))
        fd = openat2(self.fd, relative, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC,
                     BENEATH | NO_SYMLINKS | NO_MAGICLINKS | NO_XDEV)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_dev != os.fstat(self.fd).st_dev
                    or (info.st_dev, info.st_ino) in self.forbidden_inodes):
                raise FileAccessError('file unavailable')
            return fd, info
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
