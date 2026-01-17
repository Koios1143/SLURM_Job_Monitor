"""CLI entry point for SLURM monitor."""

import sys
import signal
import time
import click
import threading
import select
import tty
import termios
from typing import List, Optional
from .job_manager import JobManager
from .status_monitor import StatusMonitor
from .log_tailer import LogTailer
from .ui_renderer import MonitorUI
from .utils import get_all_job_ids_from_sacct


class MonitorController:
    """Controller that coordinates all monitoring components."""
    
    def __init__(self):
        """Initialize the controller."""
        self.job_manager = JobManager()
        self.status_monitor = StatusMonitor(self.job_manager, poll_interval=3.0)
        self.log_tailer = LogTailer(poll_interval=1.0)
        self.ui = MonitorUI()
        self.running = False
        self.auto_discover_jobs = False  # Whether to automatically discover new jobs
        self.last_job_discovery_time = 0  # Last time we checked for new jobs
        self.job_discovery_interval = 10.0  # Check for new jobs every 10 seconds
    
    def setup_signal_handlers(self):
        """Set up signal handlers for graceful shutdown."""
        def signal_handler(sig, frame):
            self._cleanup_terminal()
            self.stop()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def _cleanup_terminal(self):
        """Restore terminal settings on exit."""
        try:
            # Try to restore terminal to normal mode
            if hasattr(self, '_terminal_settings') and self._terminal_settings:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._terminal_settings)
                self._terminal_settings = None
        except Exception:
            pass
    
    def start_monitoring(self, job_ids: List[int], auto_discover: bool = False):
        """
        Start monitoring one or more jobs.
        
        Args:
            job_ids: List of job IDs to monitor
            auto_discover: If True, automatically discover and add new jobs periodically
        """
        self.auto_discover_jobs = auto_discover
        if not job_ids:
            click.echo("No jobs to monitor", err=True)
            return
        
        # Add jobs to tracking
        for job_id in job_ids:
            self.job_manager.add_tracked_job(job_id)
            self.ui.update_job_status(job_id, 'UNKNOWN', {})
        
        # Set first job as current
        if job_ids:
            self.ui.set_current_job(job_ids[0])
        
        # Start status monitoring
        def status_callback(job_id: int, status: str, info: dict):
            self.ui.update_job_status(job_id, status, info)
            
            # Update log file paths if available
            stdout_path = info.get('stdout_path', '').strip()
            stderr_path = info.get('stderr_path', '').strip()
            
            # Start log tailing for this job (even if files don't exist yet)
            if stdout_path:
                self.log_tailer.add_file(
                    f'stdout_{job_id}',
                    stdout_path,
                    lambda label, content, jid=job_id: self.ui.update_log(jid, 'stdout', content)
                )
            if stderr_path:
                self.log_tailer.add_file(
                    f'stderr_{job_id}',
                    stderr_path,
                    lambda label, content, jid=job_id: self.ui.update_log(jid, 'stderr', content)
                )
        
        self.status_monitor.start_monitoring(job_ids, status_callback)
        
        # Try to get initial job info and start log tailing
        for job_id in job_ids:
            try:
                info = self.job_manager.get_job_info(job_id)
                status = self.job_manager.get_job_status(job_id)
                self.ui.update_job_status(job_id, status, info)
                
                # Start log tailing if paths are available
                stdout_path = info.get('stdout_path', '').strip()
                stderr_path = info.get('stderr_path', '').strip()
                
                # Add files for monitoring (even if they don't exist yet)
                if stdout_path:
                    self.log_tailer.add_file(
                        f'stdout_{job_id}',
                        stdout_path,
                        lambda label, content, jid=job_id: self.ui.update_log(jid, 'stdout', content)
                    )
                if stderr_path:
                    self.log_tailer.add_file(
                        f'stderr_{job_id}',
                        stderr_path,
                        lambda label, content, jid=job_id: self.ui.update_log(jid, 'stderr', content)
                    )
            except Exception as e:
                # Silently handle errors - job might not have started yet
                # Status monitor will retry
                pass
        
        self.running = True
    
    def add_job_to_monitor(self, job_id: int):
        """Add a new job to monitoring."""
        if job_id in self.ui.get_job_ids():
            return  # Already monitoring
        
        self.job_manager.add_tracked_job(job_id)
        self.ui.update_job_status(job_id, 'UNKNOWN', {})
        
        # Add to status monitor
        def status_callback(jid: int, status: str, info: dict):
            self.ui.update_job_status(jid, status, info)
            
            stdout_path = info.get('stdout_path', '').strip()
            stderr_path = info.get('stderr_path', '').strip()
            
            if stdout_path:
                self.log_tailer.add_file(
                    f'stdout_{jid}',
                    stdout_path,
                    lambda label, content, j=jid: self.ui.update_log(j, 'stdout', content)
                )
            if stderr_path:
                self.log_tailer.add_file(
                    f'stderr_{jid}',
                    stderr_path,
                    lambda label, content, j=jid: self.ui.update_log(j, 'stderr', content)
                )
        
        self.status_monitor.add_job_to_monitor(job_id, status_callback)
        
        # Get initial info
        try:
            info = self.job_manager.get_job_info(job_id)
            status = self.job_manager.get_job_status(job_id)
            self.ui.update_job_status(job_id, status, info)
        except Exception:
            pass
    
    def remove_job_from_monitor(self, job_id: int):
        """Remove a job from monitoring."""
        if job_id not in self.ui.get_job_ids():
            return  # Not monitoring
        
        self.job_manager.remove_tracked_job(job_id)
        self.status_monitor.remove_job_from_monitor(job_id)
        self.ui.remove_job(job_id)
        
        # Remove log tailing
        self.log_tailer.remove_file(f'stdout_{job_id}')
        self.log_tailer.remove_file(f'stderr_{job_id}')
        
        # If this was the current job, switch to another
        if self.ui.current_job_id == job_id:
            remaining_jobs = self.ui.get_job_ids()
            if remaining_jobs:
                self.ui.set_current_job(remaining_jobs[0])
            else:
                self.ui.current_job_id = None
    
    def stop(self):
        """Stop all monitoring."""
        self.running = False
        self.status_monitor.stop_monitoring()
        self.log_tailer.stop_monitoring()
    
    def run(self):
        """Run the monitoring UI."""
        self.setup_signal_handlers()
        
        # Start keyboard input handler in a separate thread
        keyboard_thread = None
        try:
            if sys.stdin.isatty():
                keyboard_thread = threading.Thread(
                    target=self._keyboard_input_handler,
                    daemon=True
                )
                keyboard_thread.start()
        except Exception:
            # If keyboard input setup fails, continue without it
            pass
        
        def update_callback():
            # Check if all jobs are finished
            all_finished = True
            for job_id in self.ui.get_job_ids():
                if not self.status_monitor.is_finished(job_id):
                    all_finished = False
                    break
            
            # Optionally auto-exit when all jobs finish
            # For now, we let user exit manually with Ctrl+C
            
            # Auto-discover new jobs if enabled
            if self.auto_discover_jobs:
                current_time = time.time()
                if current_time - self.last_job_discovery_time >= self.job_discovery_interval:
                    self.last_job_discovery_time = current_time
                    try:
                        # Get all jobs from sacct
                        all_job_ids = get_all_job_ids_from_sacct()
                        current_job_ids = set(self.ui.get_job_ids())
                        
                        # Find new jobs that aren't being monitored
                        new_job_ids = [jid for jid in all_job_ids if jid not in current_job_ids]
                        
                        # Add new jobs to monitoring (preserve current focus)
                        if new_job_ids:
                            current_focus = self.ui.current_job_id
                            for new_job_id in new_job_ids:
                                self.add_job_to_monitor(new_job_id)
                            # Restore focus if it was set
                            if current_focus and current_focus in self.ui.get_job_ids():
                                self.ui.set_current_job(current_focus)
                    except Exception:
                        # Silently ignore errors in job discovery
                        pass
        
        def keyboard_check():
            """Check for keyboard input in the main loop."""
            # This will be called from the UI update loop
            # The keyboard handler thread should handle input
            pass
        
        try:
            self.ui.run_live(update_callback, keyboard_check)
        finally:
            self._cleanup_terminal()
            self.stop()
    
    def _keyboard_input_handler(self):
        """Handle keyboard input for scrolling and navigation using standard terminal input."""
        old_settings = None
        try:
            # Save terminal settings
            old_settings = termios.tcgetattr(sys.stdin)
            self._terminal_settings = old_settings  # Store for cleanup
            tty.setcbreak(sys.stdin.fileno())  # Use cbreak mode instead of raw to allow Ctrl+C
            
            while self.running:
                # Check if input is available (non-blocking)
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    try:
                        # Read one character
                        char = sys.stdin.read(1)
                        
                        # Handle escape sequences for arrow keys
                        if char == '\x1b':  # ESC character
                            # Read the next characters to determine the key
                            # Give more time for escape sequences
                            if select.select([sys.stdin], [], [], 0.2)[0]:
                                # Read available characters
                                available = []
                                # Read up to 5 characters to handle various escape sequences
                                for _ in range(5):
                                    if select.select([sys.stdin], [], [], 0.05)[0]:
                                        available.append(sys.stdin.read(1))
                                    else:
                                        break
                                
                                if available:
                                    seq = ''.join(available)
                                    # Debug: uncomment to see what sequences are received
                                    # print(f"DEBUG: Received sequence: {repr(seq)}", file=sys.stderr)
                                    
                                    if seq.startswith('[A') or seq == '[A':  # Up arrow
                                        self._handle_scroll_up()
                                    elif seq.startswith('[B') or seq == '[B':  # Down arrow
                                        self._handle_scroll_down()
                                    elif seq.startswith('[5~') or seq == '[5~':  # Page Up
                                        self._handle_scroll_up(10)
                                    elif seq.startswith('[6~') or seq == '[6~':  # Page Down
                                        self._handle_scroll_down(10)
                                    elif seq.startswith('[H') or seq == '[H':  # Home
                                        self._handle_scroll_to_top()
                                    elif seq.startswith('[F') or seq == '[F':  # End
                                        self._handle_scroll_to_bottom()
                                    elif seq.startswith('[1;5'):  # Ctrl+Arrow (some terminals)
                                        if len(seq) > 4:
                                            if seq[4] == 'A':
                                                self._handle_scroll_up(10)
                                            elif seq[4] == 'B':
                                                self._handle_scroll_down(10)
                                    elif seq.startswith('O'):  # Some terminals use O instead of [
                                        if len(seq) > 1:
                                            if seq[1] == 'A':  # Up
                                                self._handle_scroll_up()
                                            elif seq[1] == 'B':  # Down
                                                self._handle_scroll_down()
                        elif char == '\t':  # Tab
                            self._handle_switch_focus()
                        elif char == 'q' or char == 'Q':  # 'q' to exit scroll mode
                            self._handle_exit_scroll_mode()
                        elif char == 'a' or char == 'A':  # 'a' to add a job
                            self._handle_add_job()
                        elif char == 'd' or char == 'D':  # 'd' to remove current job
                            self._handle_remove_job()
                        elif char == 'n' or char == 'N':  # 'n' to switch to next job
                            self._handle_next_job()
                        elif char == 'p' or char == 'P':  # 'p' to switch to previous job
                            self._handle_previous_job()
                        elif char == '\x03':  # Ctrl+C
                            self.stop()
                            break
                    except Exception as e:
                        # Ignore read errors, but could log for debugging
                        pass
        except Exception:
            # If keyboard handling fails, continue without it
            pass
        finally:
            # Restore terminal settings
            if old_settings:
                try:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    self._terminal_settings = None
                except Exception:
                    pass
    
    def _handle_switch_focus(self):
        """Handle focus switch action."""
        try:
            self.ui.switch_focus()
        except Exception:
            pass
    
    def _handle_scroll_up(self, lines: int = 1):
        """Handle scroll up action for focused panel."""
        try:
            self.ui.scroll_up(lines)
        except Exception:
            pass
    
    def _handle_scroll_down(self, lines: int = 1):
        """Handle scroll down action for focused panel."""
        try:
            self.ui.scroll_down(lines)
        except Exception:
            pass
    
    def _handle_scroll_to_bottom(self):
        """Handle scroll to bottom action for focused panel."""
        try:
            self.ui.scroll_to_bottom()
        except Exception:
            pass
    
    def _handle_scroll_to_top(self):
        """Handle scroll to top action for focused panel."""
        try:
            self.ui.scroll_to_top()
        except Exception:
            pass
    
    def _handle_exit_scroll_mode(self):
        """Handle exit scroll mode action (press 'q')."""
        try:
            if self.ui.current_job_id:
                panel = self.ui.focused_panel
                self.ui.exit_scroll_mode(self.ui.current_job_id, panel)
        except Exception:
            pass
    
    def _handle_add_job(self):
        """Handle add job action (press 'a')."""
        # Note: Adding jobs interactively requires more complex input handling
        # For now, users can add jobs by restarting with additional job IDs
        # A future enhancement could add a proper input prompt
        pass
    
    def _handle_remove_job(self):
        """Handle remove current job action (press 'd')."""
        try:
            if self.ui.current_job_id:
                job_id = self.ui.current_job_id
                self.remove_job_from_monitor(job_id)
        except Exception:
            pass
    
    def _handle_next_job(self):
        """Handle switch to next job action (press 'n')."""
        try:
            self.ui.switch_to_next_job()
        except Exception:
            pass
    
    def _handle_previous_job(self):
        """Handle switch to previous job action (press 'p')."""
        try:
            self.ui.switch_to_previous_job()
        except Exception:
            pass


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """SLURM Job Monitor - Real-time monitoring tool for SLURM jobs."""
    pass


@cli.command()
@click.argument('script', type=click.Path(exists=True))
@click.option('--no-watch', is_flag=True, default=False, help='Do not start monitoring after submission')
def submit(script: str, no_watch: bool):
    """Submit a SLURM job script and optionally start monitoring."""
    try:
        job_manager = JobManager()
        job_id = job_manager.submit_job(script)
        
        if job_id:
            click.echo(f"Submitted job {job_id}")
            
            if not no_watch:
                click.echo("Starting monitor...")
                controller = MonitorController()
                controller.start_monitoring([job_id])
                controller.run()
            else:
                click.echo(f"Job {job_id} submitted. Use 'slurm-monitor watch {job_id}' to monitor it.")
        else:
            click.echo("Failed to submit job: Could not parse job ID", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error submitting job: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('job_ids', nargs=-1, type=int, required=False)
def watch(job_ids: tuple):
    """Monitor one or more existing SLURM jobs. If no job IDs provided, monitors all visible jobs from sacct and auto-discovers new jobs."""
    try:
        # If no job IDs provided, get all jobs from sacct and enable auto-discovery
        auto_discover = False
        if not job_ids:
            click.echo("No job IDs provided. Fetching all visible jobs from sacct...")
            all_job_ids = get_all_job_ids_from_sacct()
            if not all_job_ids:
                click.echo("No jobs found in sacct. Will monitor for new jobs...")
                all_job_ids = []
            else:
                click.echo(f"Found {len(all_job_ids)} job(s): {', '.join(map(str, all_job_ids))}")
            job_ids = all_job_ids
            auto_discover = True
            click.echo("Auto-discovery enabled: new jobs will be automatically added to monitoring.")
        
        controller = MonitorController()
        controller.start_monitoring(list(job_ids), auto_discover=auto_discover)
        controller.run()
    except KeyboardInterrupt:
        click.echo("\nStopping monitor...")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command(name='list')
def list_jobs():
    """List all currently tracked jobs."""
    try:
        job_manager = JobManager()
        tracked = job_manager.list_tracked_jobs()
        
        if not tracked:
            click.echo("No tracked jobs")
            return
        
        click.echo("Tracked jobs:")
        for job_id in tracked:
            status = job_manager.get_job_status(job_id)
            info = job_manager.get_job_info(job_id)
            job_name = info.get('job_name', 'N/A')
            click.echo(f"  {job_id}: {status} - {job_name}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument('job_id', type=int)
def stop(job_id: int):
    """Stop monitoring a specific job (does not cancel the job)."""
    try:
        job_manager = JobManager()
        job_manager.remove_tracked_job(job_id)
        click.echo(f"Stopped tracking job {job_id}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def main():
    """Main entry point."""
    cli()


if __name__ == '__main__':
    main()
