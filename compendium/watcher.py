import os
from PyQt5.QtCore import QObject, QTimer, pyqtSignal, Qt, QFileSystemWatcher


class CompendiumWatcher(QObject):
    """Small wrapper around QFileSystemWatcher that debounces rapid changes.

    API:
      - set_callback(callable(path)) : set the function called after debounce
      - clear(): remove all watched paths
      - add_watch(path): add a file or directory to watch
    """

    def __init__(self, parent=None, interval_ms: int = 250):
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_path_changed)
        self._watcher.directoryChanged.connect(self._on_path_changed)
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.setInterval(interval_ms)
        self._reload_timer.timeout.connect(self._on_timeout)
        self._callback = None
        self._pending_path = None

    def set_callback(self, callback):
        self._callback = callback

    def clear(self):
        # remove watched files and directories
        for p in list(self._watcher.files()):
            try:
                self._watcher.removePath(p)
            except Exception:
                pass
        for p in list(self._watcher.directories()):
            try:
                self._watcher.removePath(p)
            except Exception:
                pass

    def add_watch(self, path: str):
        if not path:
            return
        try:
            if os.path.exists(path):
                # QFileSystemWatcher accepts files or directories
                if path not in self._watcher.files() and path not in self._watcher.directories():
                    self._watcher.addPath(path)
        except Exception:
            pass

    def _on_path_changed(self, path: str):
        # schedule a debounced callback
        self._pending_path = path
        if self._reload_timer.isActive():
            self._reload_timer.stop()
        self._reload_timer.start()

    def _on_timeout(self):
        if self._callback:
            try:
                self._callback(self._pending_path)
            except Exception:
                pass
