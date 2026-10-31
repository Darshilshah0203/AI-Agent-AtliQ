"""Process-level single instance lock for Windows."""

import os
import sys
import msvcrt
from typing import Optional


class SingleInstanceError(Exception):
    """Raised when another agent instance is already executing."""
    pass


class SingleInstanceLock:
    """Windows process lock using msvcrt file locking on agent.lock."""

    def __init__(self, lock_path: str = "agent.lock"):
        self.lock_path = lock_path
        self.handle: Optional[Any] = None

    def __enter__(self):
        try:
            self.handle = open(self.lock_path, "a+")
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            return self
        except OSError:
            if self.handle:
                try:
                    self.handle.close()
                except Exception:
                    pass
            raise SingleInstanceError(
                f"Another instance of AtliQ Morning Digest Agent is currently executing (lock '{self.lock_path}'). "
                "Only one instance may run at a time."
            )

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handle:
            try:
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            try:
                self.handle.close()
            except Exception:
                pass

        if os.path.exists(self.lock_path):
            try:
                os.remove(self.lock_path)
            except Exception:
                pass

