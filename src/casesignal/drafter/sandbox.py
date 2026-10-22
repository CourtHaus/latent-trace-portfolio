"""Fail-closed Linux confinement for generated Python, installed before collection.

Landlock restricts filesystem access. Seccomp denies network and process creation
even if generated code calls libc directly. No host home, Git metadata, credentials,
or operator checkout is granted merely because the subprocess inherits its uid.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import platform
import resource
import sys
from pathlib import Path


class IsolationUnavailable(RuntimeError):
    pass


class _PathRule(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("access", ctypes.c_uint64), ("fd", ctypes.c_int32)]


def confine(root: Path, scratch: Path) -> None:
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "aarch64"}:
        raise IsolationUnavailable("grading requires Linux Landlock ABI 3+ and libseccomp")
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise IsolationUnavailable("grading requires Linux Landlock ABI 3+ (kernel 6.2+)")
    library = ctypes.util.find_library("seccomp")
    if not library:
        raise IsolationUnavailable("grading requires libseccomp.so.2")
    sec = ctypes.CDLL(library, use_errno=True)
    sec.seccomp_init.argtypes = [ctypes.c_uint32]
    sec.seccomp_init.restype = ctypes.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    sec.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    sec.seccomp_load.argtypes = [ctypes.c_void_p]
    sec.seccomp_release.argtypes = [ctypes.c_void_p]
    context = sec.seccomp_init(0x7FFF0000)
    if not context:
        raise IsolationUnavailable("cannot initialize seccomp")
    try:
        for name in (
            "socket",
            "socketpair",
            "connect",
            "bind",
            "listen",
            "accept",
            "accept4",
            "execve",
            "execveat",
            "fork",
            "vfork",
            "clone",
            "clone3",
            "ptrace",
            "process_vm_readv",
            "process_vm_writev",
            "kill",
            "tkill",
            "tgkill",
            "pidfd_open",
            "pidfd_getfd",
            "pidfd_send_signal",
            "mount",
            "umount2",
            "unshare",
            "setns",
            "bpf",
            "io_uring_setup",
            "open_by_handle_at",
        ):
            number = sec.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and sec.seccomp_rule_add(context, 0x50000 | errno.EPERM, number, 0):
                raise IsolationUnavailable(f"cannot deny syscall {name}")
        # ABI 3 filesystem rights, including REFER and TRUNCATE.
        handled = ctypes.c_uint64((1 << 15) - 1)
        ruleset = libc.syscall(444, ctypes.byref(handled), ctypes.sizeof(handled), 0)
        if ruleset < 0:
            raise IsolationUnavailable("cannot create Landlock ruleset")
        try:
            read = (1 << 2) | (1 << 3)
            # Grant code/runtime libraries, not the home directories containing them.
            roots = {
                Path(sys.prefix),
                Path(sys.base_prefix),
                root,
                Path("/usr"),
                Path("/lib"),
                Path("/lib64"),
            }
            for path, access in [(p, read) for p in roots] + [
                (scratch, handled.value & ~1),
                (Path("/dev/null"), (1 << 1) | (1 << 2)),
            ]:
                if not path.exists():
                    continue
                fd = os.open(path.resolve(), os.O_PATH | os.O_CLOEXEC)
                try:
                    rule = _PathRule(access, fd)
                    if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) < 0:
                        raise IsolationUnavailable(f"cannot grant sandbox path {path}")
                finally:
                    os.close(fd)
            if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.syscall(446, ruleset, 0) < 0:
                raise IsolationUnavailable("cannot enforce Landlock ruleset")
        finally:
            os.close(ruleset)
        if sec.seccomp_load(context) != 0:
            raise IsolationUnavailable("cannot enforce seccomp ruleset")
    finally:
        sec.seccomp_release(context)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (64 * 1024**2, 64 * 1024**2))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
