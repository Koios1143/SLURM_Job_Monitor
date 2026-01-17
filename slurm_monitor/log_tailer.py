"""Log Tailer for real-time monitoring of stdout/stderr files."""

import os
import time
from typing import Dict, Callable, Optional, Set
from threading import Thread, Event, Lock
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent


class LogFileHandler(FileSystemEventHandler):
    """Handler for file modification events."""
    
    def __init__(self, callback: Callable[[str, str], None], file_path: str):
        """
        Initialize the file handler.
        
        Args:
            callback: Function to call with (file_path, new_content)
            file_path: Path to the file being monitored
        """
        self.callback = callback
        self.file_path = file_path
        self.last_position = 0
        self.initial_read_done = False
    
    def read_existing_content(self):
        """Read existing content from file if it exists. Called after handler is set up."""
        if self.initial_read_done:
            return
        
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    existing_content = f.read()
                    if existing_content:
                        self.callback(self.file_path, existing_content)
                    self.last_position = f.tell()
                    self.initial_read_done = True
            except (IOError, OSError, PermissionError):
                # If we can't read, start from beginning
                self.last_position = 0
                self.initial_read_done = True
        else:
            self.initial_read_done = True
    
    def on_modified(self, event):
        """Handle file modification events."""
        if not event.is_directory and event.src_path == self.file_path:
            self._read_new_content()
    
    def _read_new_content(self):
        """Read new content from the file since last read."""
        if not os.path.exists(self.file_path):
            # Reset position if file was deleted and recreated
            self.last_position = 0
            return
        
        try:
            current_size = os.path.getsize(self.file_path)
            
            # If file was truncated or recreated, reset position
            if current_size < self.last_position:
                self.last_position = 0
            
            with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                # Seek to last known position
                f.seek(self.last_position)
                
                # Read new content
                new_content = f.read()
                
                if new_content:
                    self.callback(self.file_path, new_content)
                    self.last_position = f.tell()
        except (IOError, OSError, PermissionError):
            # File might be locked, deleted, or permission denied
            # Silently ignore and retry later
            pass
        except Exception:
            # Catch any other unexpected errors
            pass
    
    def check_for_updates(self):
        """Manually check for file updates (fallback if watchdog fails)."""
        self._read_new_content()


class LogTailer:
    """Monitors stdout/stderr files for real-time updates."""
    
    def __init__(self, poll_interval: float = 1.0):
        """
        Initialize the LogTailer.
        
        Args:
            poll_interval: Polling interval in seconds for fallback mode (default: 1.0)
        """
        self.poll_interval = poll_interval
        self.observers: Dict[str, Observer] = {}
        self.handlers: Dict[str, LogFileHandler] = {}
        self.log_callbacks: Dict[str, Callable[[str, str], None]] = {}
        self.monitoring = False
        self.monitor_thread: Optional[Thread] = None
        self.stop_event = Event()
        self.lock = Lock()
        self.use_watchdog = True
        
        # Try to use watchdog, fallback to polling if it fails
        try:
            self.observer = Observer()
            self.observer.start()
        except Exception:
            self.use_watchdog = False
    
    def start_monitoring(self, file_paths: Dict[str, str], 
                        callback: Optional[Callable[[str, str], None]] = None):
        """
        Start monitoring one or more log files.
        
        Args:
            file_paths: Dictionary mapping labels to file paths, e.g., {'stdout': '/path/to/out', 'stderr': '/path/to/err'}
            callback: Optional callback function(file_label, new_content) called on new content
        """
        if self.monitoring:
            self.stop_monitoring()
        
        self.stop_event.clear()
        self.monitoring = True
        
        with self.lock:
            for label, file_path in file_paths.items():
                if not file_path:
                    continue
                
                # Register callback
                if callback:
                    self.log_callbacks[label] = callback
                
                # Create handler
                handler = LogFileHandler(
                    lambda path, content, lbl=label: self._on_file_update(lbl, content),
                    file_path
                )
                self.handlers[label] = handler
                
                # Start watching with watchdog if available
                if self.use_watchdog and os.path.exists(os.path.dirname(file_path)):
                    observer = Observer()
                    observer.schedule(handler, os.path.dirname(file_path), recursive=False)
                    observer.start()
                    self.observers[label] = observer
                else:
                    # Fallback to polling mode
                    self.use_watchdog = False
        
        # Always start polling thread as fallback (works even if watchdog is used)
        # This ensures we catch updates even if watchdog misses them
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = Thread(target=self._poll_loop, daemon=True)
            self.monitor_thread.start()
    
    def _on_file_update(self, label: str, content: str):
        """Handle file update event."""
        if label in self.log_callbacks:
            try:
                self.log_callbacks[label](label, content)
            except Exception as e:
                # Don't let callback errors break monitoring
                print(f"Error in log callback for {label}: {e}")
    
    def _poll_loop(self):
        """Polling loop for file updates (fallback mode)."""
        while self.monitoring and not self.stop_event.is_set():
            with self.lock:
                for label, handler in list(self.handlers.items()):
                    try:
                        handler.check_for_updates()
                    except Exception:
                        # Continue monitoring other files even if one fails
                        pass
            
            self.stop_event.wait(self.poll_interval)
    
    def stop_monitoring(self):
        """Stop monitoring all files."""
        self.monitoring = False
        self.stop_event.set()
        
        # Stop all observers
        with self.lock:
            for observer in self.observers.values():
                observer.stop()
                observer.join(timeout=1.0)
            self.observers.clear()
            self.handlers.clear()
            self.log_callbacks.clear()
        
        # Stop polling thread
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
    
    def add_file(self, label: str, file_path: str, callback: Optional[Callable[[str, str], None]] = None):
        """
        Add a file to monitor.
        
        Args:
            label: Label for the file (e.g., 'stdout', 'stderr')
            file_path: Path to the file
            callback: Optional callback function
        """
        if not file_path or not file_path.strip():
            return
        
        # Normalize path
        file_path = os.path.abspath(os.path.expanduser(file_path))
        
        with self.lock:
            # Remove existing monitoring for this label if it exists
            if label in self.observers:
                self.observers[label].stop()
                self.observers[label].join(timeout=1.0)
                del self.observers[label]
            
            if label in self.handlers:
                del self.handlers[label]
            
            if callback:
                self.log_callbacks[label] = callback
            
            handler = LogFileHandler(
                lambda path, content, lbl=label: self._on_file_update(lbl, content),
                file_path
            )
            self.handlers[label] = handler
            
            # Read existing content after handler is set up
            handler.read_existing_content()
            
            # Try to set up watchdog monitoring
            file_dir = os.path.dirname(file_path)
            if self.use_watchdog and file_dir and os.path.exists(file_dir):
                try:
                    observer = Observer()
                    observer.schedule(handler, file_dir, recursive=False)
                    observer.start()
                    self.observers[label] = observer
                except Exception:
                    # If watchdog fails, fall back to polling
                    self.use_watchdog = False
            
            # If watchdog not used or failed, ensure polling is active
            if label not in self.observers:
                # Will be handled by polling thread
                pass
    
    def remove_file(self, label: str):
        """
        Remove a file from monitoring.
        
        Args:
            label: Label of the file to remove
        """
        with self.lock:
            if label in self.observers:
                self.observers[label].stop()
                self.observers[label].join(timeout=1.0)
                del self.observers[label]
            
            if label in self.handlers:
                del self.handlers[label]
            
            if label in self.log_callbacks:
                del self.log_callbacks[label]
