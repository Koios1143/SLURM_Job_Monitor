"""Status Monitor for polling SLURM job status."""

import time
from typing import Dict, Callable, Optional
from threading import Thread, Event
from .job_manager import JobManager


class StatusMonitor:
    """Monitors SLURM job status with periodic polling."""
    
    def __init__(self, job_manager: JobManager, poll_interval: float = 3.0):
        """
        Initialize the StatusMonitor.
        
        Args:
            job_manager: JobManager instance
            poll_interval: Polling interval in seconds (default: 3.0)
        """
        self.job_manager = job_manager
        self.poll_interval = poll_interval
        self.monitoring = False
        self.monitor_thread: Optional[Thread] = None
        self.stop_event = Event()
        self.status_callbacks: Dict[int, Callable[[int, str, Dict], None]] = {}
        self.current_statuses: Dict[int, Dict] = {}
    
    def start_monitoring(self, job_ids: list[int], callback: Optional[Callable[[int, str, Dict], None]] = None):
        """
        Start monitoring one or more jobs.
        
        Args:
            job_ids: List of job IDs to monitor
            callback: Optional callback function(job_id, status, info) called on status updates
        """
        if self.monitoring:
            self.stop_monitoring()
        
        self.stop_event.clear()
        self.monitoring = True
        
        # Register callbacks for each job
        for job_id in job_ids:
            if callback:
                self.status_callbacks[job_id] = callback
            self.current_statuses[job_id] = {}
        
        # Start monitoring thread
        self.monitor_thread = Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop the monitoring thread."""
        self.monitoring = False
        self.stop_event.set()
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2.0)
        self.status_callbacks.clear()
        self.current_statuses.clear()
    
    def _monitor_loop(self):
        """Main monitoring loop running in a separate thread."""
        while self.monitoring and not self.stop_event.is_set():
            for job_id in list(self.current_statuses.keys()):
                try:
                    # Get current status
                    status = self.job_manager.get_job_status(job_id)
                    info = self.job_manager.get_job_info(job_id)
                    
                    # Check if status changed
                    old_status = self.current_statuses[job_id].get('status')
                    if status != old_status or not self.current_statuses[job_id]:
                        self.current_statuses[job_id] = {
                            'status': status,
                            'info': info,
                        }
                        
                    # Call callback if registered
                    if job_id in self.status_callbacks:
                        try:
                            self.status_callbacks[job_id](job_id, status, info)
                        except Exception:
                            # Don't let callback errors break monitoring
                            # Silently continue
                            pass
                    
                    # Update info even if status didn't change (for runtime updates)
                    self.current_statuses[job_id]['info'] = info
                    
                except Exception:
                    # Silently continue monitoring other jobs
                    # Errors are often transient (job not found yet, etc.)
                    pass
            
            # Wait for poll interval or until stop event
            self.stop_event.wait(self.poll_interval)
    
    def add_job_to_monitor(self, job_id: int, callback: Optional[Callable[[int, str, Dict], None]] = None):
        """
        Add a job to monitoring.
        
        Args:
            job_id: The SLURM job ID
            callback: Optional callback function(job_id, status, info) called on status updates
        """
        if callback:
            self.status_callbacks[job_id] = callback
        self.current_statuses[job_id] = {}
    
    def remove_job_from_monitor(self, job_id: int):
        """
        Remove a job from monitoring.
        
        Args:
            job_id: The SLURM job ID
        """
        if job_id in self.status_callbacks:
            del self.status_callbacks[job_id]
        if job_id in self.current_statuses:
            del self.current_statuses[job_id]
    
    def get_status(self, job_id: int) -> Optional[Dict]:
        """
        Get the current cached status for a job.
        
        Args:
            job_id: The SLURM job ID
            
        Returns:
            Dictionary with status and info, or None if not monitored
        """
        return self.current_statuses.get(job_id)
    
    def is_finished(self, job_id: int) -> bool:
        """
        Check if a job has finished (completed or failed).
        
        Args:
            job_id: The SLURM job ID
            
        Returns:
            True if job is finished, False otherwise
        """
        status_info = self.current_statuses.get(job_id)
        if status_info:
            status = status_info.get('status', '')
            return status in ('COMPLETED', 'FAILED')
        return False
