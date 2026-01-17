"""UI Renderer using Rich library for terminal interface."""

import time
from typing import Dict, Optional, List
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.align import Align
from rich import box


class MonitorUI:
    """Rich-based UI for monitoring SLURM jobs."""
    
    def __init__(self):
        """Initialize the MonitorUI."""
        self.console = Console()
        self.layout = None
        self.job_data: Dict[int, Dict] = {}
        self.log_data: Dict[int, Dict[str, str]] = {}  # {job_id: {'stdout': '', 'stderr': ''}}
        self.current_job_id: Optional[int] = None
        self.stdout_scroll_pos: Dict[int, int] = {}  # Track scroll position per job (line number)
        self.stderr_scroll_pos: Dict[int, int] = {}  # Track scroll position per job (line number)
        self.stdout_lines: Dict[int, List[str]] = {}  # Cached lines for scrolling
        self.stderr_lines: Dict[int, List[str]] = {}  # Cached lines for scrolling
        self.focused_panel: str = 'stdout'  # 'stdout' or 'stderr' - which panel has focus
        self.scroll_mode: Dict[int, Dict[str, bool]] = {}  # Track if in scroll mode per job/panel
        self._cached_max_lines_per_panel: Optional[int] = None  # Cache max lines per panel
        self._setup_layout()
    
    def _setup_layout(self):
        """Set up the UI layout structure."""
        self.layout = Layout()
        
        # Split into header and body
        self.layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body")
        )
        
        # Split body into status and output
        self.layout["body"].split_row(
            Layout(name="status_panel", ratio=1),
            Layout(name="output_panel", ratio=2)
        )
    
    def update_job_status(self, job_id: int, status: str, info: Dict):
        """
        Update job status information.
        
        Args:
            job_id: The SLURM job ID
            status: Current job status
            info: Job information dictionary
        """
        if job_id not in self.job_data:
            self.job_data[job_id] = {}
        
        self.job_data[job_id]['status'] = status
        self.job_data[job_id]['info'] = info
        
        # Set as current job if not set
        if self.current_job_id is None:
            self.current_job_id = job_id
    
    def update_log(self, job_id: int, log_type: str, new_content: str):
        """
        Update log content for a job.
        
        Args:
            job_id: The SLURM job ID
            log_type: 'stdout' or 'stderr'
            new_content: New log content to append
        """
        if job_id not in self.log_data:
            self.log_data[job_id] = {'stdout': '', 'stderr': ''}
        
        if log_type in self.log_data[job_id]:
            # Store old line count and scroll position before update
            old_line_count = 0
            old_scroll_pos = 0
            if log_type == 'stdout' and job_id in self.stdout_lines:
                old_line_count = len(self.stdout_lines[job_id])
                old_scroll_pos = self.stdout_scroll_pos.get(job_id, 0)
            elif log_type == 'stderr' and job_id in self.stderr_lines:
                old_line_count = len(self.stderr_lines[job_id])
                old_scroll_pos = self.stderr_scroll_pos.get(job_id, 0)
            
            self.log_data[job_id][log_type] += new_content
            
            # Update cached lines for scrolling - rebuild from full content for accuracy
            if log_type == 'stdout':
                # Rebuild lines from full content to handle edge cases
                full_content = self.log_data[job_id][log_type]
                new_lines = full_content.split('\n')
                self.stdout_lines[job_id] = new_lines
                
                # Check if we're in scroll mode - if so, preserve scroll position
                is_in_scroll = self.is_in_scroll_mode(job_id, 'stdout')
                
                if is_in_scroll:
                    # In scroll mode: preserve the scroll position (don't auto-scroll)
                    # The scroll position is already set, just ensure it's within bounds
                    # This will be handled by _get_visible_lines
                    pass
                else:
                    # Not in scroll mode: auto-scroll to bottom only if we were already at/near bottom
                    if self._cached_max_lines_per_panel is None:
                        try:
                            terminal_height = self.console.height
                            available_height = terminal_height - 3 - 4
                            self._cached_max_lines_per_panel = max(5, available_height // 2 - 2)
                        except Exception:
                            self._cached_max_lines_per_panel = 20
                    max_lines_per_panel = self._cached_max_lines_per_panel
                    
                    # Calculate if we were at the bottom before the update
                    # We were at bottom if: old_line_count <= max_lines_per_panel OR
                    #                        old_scroll_pos >= (old_line_count - max_lines_per_panel - 2)
                    if old_line_count == 0:
                        # First content, scroll to bottom
                        self.scroll_to_bottom_stdout()
                    elif old_line_count <= max_lines_per_panel:
                        # Content was short enough to fit in one screen, we were at bottom
                        self.scroll_to_bottom_stdout()
                    else:
                        # Content was longer, check if we were near the bottom
                        old_max_scroll = old_line_count - max_lines_per_panel
                        # We were at bottom if scroll position was within 2 lines of max
                        if old_scroll_pos >= old_max_scroll - 2:
                            self.scroll_to_bottom_stdout()
                        # Otherwise, keep the current scroll position (user was viewing earlier content)
            elif log_type == 'stderr':
                full_content = self.log_data[job_id][log_type]
                new_lines = full_content.split('\n')
                self.stderr_lines[job_id] = new_lines
                
                # Check if we're in scroll mode - if so, preserve scroll position
                is_in_scroll = self.is_in_scroll_mode(job_id, 'stderr')
                
                if is_in_scroll:
                    # In scroll mode: preserve the scroll position (don't auto-scroll)
                    # The scroll position is already set, just ensure it's within bounds
                    # This will be handled by _get_visible_lines
                    pass
                else:
                    # Not in scroll mode: auto-scroll to bottom only if we were already at/near bottom
                    if self._cached_max_lines_per_panel is None:
                        try:
                            terminal_height = self.console.height
                            available_height = terminal_height - 3 - 4
                            self._cached_max_lines_per_panel = max(5, available_height // 2 - 2)
                        except Exception:
                            self._cached_max_lines_per_panel = 20
                    max_lines_per_panel = self._cached_max_lines_per_panel
                    
                    # Calculate if we were at the bottom before the update
                    # We were at bottom if: old_line_count <= max_lines_per_panel OR
                    #                        old_scroll_pos >= (old_line_count - max_lines_per_panel - 2)
                    if old_line_count == 0:
                        # First content, scroll to bottom
                        self.scroll_to_bottom_stderr()
                    elif old_line_count <= max_lines_per_panel:
                        # Content was short enough to fit in one screen, we were at bottom
                        self.scroll_to_bottom_stderr()
                    else:
                        # Content was longer, check if we were near the bottom
                        old_max_scroll = old_line_count - max_lines_per_panel
                        # We were at bottom if scroll position was within 2 lines of max
                        if old_scroll_pos >= old_max_scroll - 2:
                            self.scroll_to_bottom_stderr()
                        # Otherwise, keep the current scroll position (user was viewing earlier content)
    
    def is_in_scroll_mode(self, job_id: int, panel: str) -> bool:
        """Check if a panel is in scroll mode (user has manually scrolled)."""
        if job_id not in self.scroll_mode:
            return False
        return self.scroll_mode[job_id].get(panel, False)
    
    def set_scroll_mode(self, job_id: int, panel: str, enabled: bool):
        """Set scroll mode for a panel."""
        if job_id not in self.scroll_mode:
            self.scroll_mode[job_id] = {}
        self.scroll_mode[job_id][panel] = enabled
    
    def exit_scroll_mode(self, job_id: int, panel: str):
        """Exit scroll mode and scroll to bottom."""
        self.set_scroll_mode(job_id, panel, False)
        if panel == 'stdout':
            self.scroll_to_bottom_stdout()
        else:
            self.scroll_to_bottom_stderr()
    
    def set_current_job(self, job_id: int):
        """
        Set the currently displayed job.
        
        Args:
            job_id: The SLURM job ID to display
        """
        if job_id in self.job_data:
            self.current_job_id = job_id
    
    def _render_header(self) -> Panel:
        """Render the header panel."""
        if not self.job_data:
            return Panel("No jobs being monitored", title="SLURM Job Monitor", border_style="blue")
        
        job_count = len(self.job_data)
        title = f"SLURM Job Monitor - {job_count} job{'s' if job_count > 1 else ''}"
        
        # Show current job if set
        if self.current_job_id and self.current_job_id in self.job_data:
            current_info = self.job_data[self.current_job_id].get('info', {})
            job_name = current_info.get('job_name', f'Job {self.current_job_id}')
            title += f" | Current: {job_name} (ID: {self.current_job_id})"
        
        # Add help text
        help_text = "Press Ctrl+C to exit | Scroll with mouse or arrow keys"
        
        content = Text()
        content.append(title, style="bold blue")
        content.append("\n")
        content.append(help_text, style="dim")
        
        return Panel(
            Align.center(content),
            border_style="blue"
        )
    
    def _render_status_panel(self) -> Panel:
        """Render the status panel."""
        if not self.job_data:
            return Panel("No jobs", title="Job Status", border_style="yellow")
        
        # Create table for job statuses
        table = Table(show_header=True, header_style="bold magenta", box=box.SIMPLE)
        table.add_column("Job ID", style="cyan", width=10)
        table.add_column("Status", width=12)
        table.add_column("Runtime", width=12)
        table.add_column("Name", width=20)
        
        # Sort jobs by ID in descending order (largest to smallest)
        for job_id in sorted(self.job_data.keys(), reverse=True):
            data = self.job_data[job_id]
            status = data.get('status', 'UNKNOWN')
            info = data.get('info', {})
            
            # Color code status
            status_style = {
                'QUEUED': 'yellow',
                'RUNNING': 'green',
                'COMPLETED': 'blue',
                'FAILED': 'red',
                'UNKNOWN': 'white',
            }.get(status, 'white')
            
            runtime = info.get('elapsed', 'N/A')
            job_name = info.get('job_name', f'Job {job_id}')
            
            # Highlight current job with more visible indicator
            is_current = job_id == self.current_job_id
            row_style = "bold bright_white on blue" if is_current else None
            
            # Add indicator for current job
            job_id_display = f"▶ {job_id}" if is_current else str(job_id)
            
            # First row: Job ID, Status, Runtime, Name
            table.add_row(
                job_id_display,
                Text(status, style=status_style),
                runtime,
                job_name,
                style=row_style
            )
        
        # Add usage instructions at the bottom
        help_text = Text()
        help_text.append("n: next job | p: prev job | d: remove job", style="dim")
        
        # Create a container with table and help text
        from rich.console import Group
        content = Group(table, help_text)
        
        return Panel(content, title="Job Status", border_style="yellow")
    
    def _get_visible_lines(self, lines: List[str], scroll_pos: int, max_height: int) -> tuple[List[str], int, int]:
        """
        Get visible lines based on scroll position.
        
        Args:
            lines: All lines of content
            scroll_pos: Current scroll position (line index)
            max_height: Maximum number of lines to display
            
        Returns:
            Tuple of (visible_lines, start_line, end_line)
        """
        total_lines = len(lines)
        if total_lines == 0:
            return (["[No output yet - waiting for file updates...]"], 0, 0)
        
        # Ensure scroll_pos is within bounds
        max_scroll = max(0, total_lines - max_height)
        scroll_pos = max(0, min(scroll_pos, max_scroll))
        
        # Get visible range
        start = scroll_pos
        end = min(start + max_height, total_lines)
        
        visible = lines[start:end]
        return (visible, start, end)
    
    def _render_output_panel(self) -> Layout:
        """Render the output panel with stdout and stderr."""
        if not self.current_job_id or self.current_job_id not in self.job_data:
            return Layout(Panel("Select a job to view output", title="Output", border_style="green"))
        
        job_id = self.current_job_id
        
        # Create layout for stdout and stderr
        output_layout = Layout()
        output_layout.split_column(
            Layout(name="stdout", ratio=1),
            Layout(name="stderr", ratio=1)
        )
        
        # Get terminal size for calculating visible lines
        # Cache the value to avoid recalculation causing position jumps
        try:
            terminal_height = self.console.height
            # Reserve space for header (3) and borders (2 per panel = 4)
            available_height = terminal_height - 3 - 4
            calculated_max = max(5, available_height // 2 - 2)  # Reserve 2 lines for panel borders
            # Only update cache if terminal size changed significantly (more than 2 lines difference)
            if self._cached_max_lines_per_panel is None or abs(self._cached_max_lines_per_panel - calculated_max) > 2:
                self._cached_max_lines_per_panel = calculated_max
            max_lines_per_panel = self._cached_max_lines_per_panel
        except Exception:
            if self._cached_max_lines_per_panel is None:
                self._cached_max_lines_per_panel = 20  # Default fallback
            max_lines_per_panel = self._cached_max_lines_per_panel
        
        # Initialize scroll positions if not set
        if job_id not in self.stdout_scroll_pos:
            self.stdout_scroll_pos[job_id] = 0
        if job_id not in self.stderr_scroll_pos:
            self.stderr_scroll_pos[job_id] = 0
        
        # Get or build stdout lines
        if job_id not in self.stdout_lines:
            stdout_content = self.log_data.get(job_id, {}).get('stdout', '')
            if stdout_content:
                self.stdout_lines[job_id] = stdout_content.split('\n')
            else:
                self.stdout_lines[job_id] = []
        
        # Get visible stdout lines
        stdout_visible, stdout_start, stdout_end = self._get_visible_lines(
            self.stdout_lines[job_id],
            self.stdout_scroll_pos[job_id],
            max_lines_per_panel
        )
        stdout_display = '\n'.join(stdout_visible)
        
        # Highlight focused panel with brighter colors when focused, dimmer when not
        is_focused = self.focused_panel == 'stdout'
        if is_focused:
            border_style_stdout = "bright_green"
            title_style = "bold bright_green"
            focus_indicator = " [FOCUSED]"
        else:
            border_style_stdout = "dim green"
            title_style = "dim green"
            focus_indicator = " [Press Tab to focus]"
        
        # Add scroll mode indicator
        scroll_mode_indicator = ""
        if self.is_in_scroll_mode(job_id, 'stdout'):
            scroll_mode_indicator = " [SCROLL MODE - Press 'q' to exit]"
        
        stdout_panel = Panel(
            stdout_display,
            title=f"[{title_style}]STDOUT[/{title_style}] (Job {job_id}){focus_indicator}{scroll_mode_indicator} | Tab to switch, ↑↓ to scroll, q to exit scroll",
            border_style=border_style_stdout,
            title_align="left"
        )
        output_layout["stdout"].update(stdout_panel)
        
        # Get or build stderr lines
        if job_id not in self.stderr_lines:
            stderr_content = self.log_data.get(job_id, {}).get('stderr', '')
            if stderr_content:
                self.stderr_lines[job_id] = stderr_content.split('\n')
            else:
                self.stderr_lines[job_id] = []
        
        # Get visible stderr lines
        stderr_visible, stderr_start, stderr_end = self._get_visible_lines(
            self.stderr_lines[job_id],
            self.stderr_scroll_pos[job_id],
            max_lines_per_panel
        )
        stderr_display = '\n'.join(stderr_visible)
        
        # Highlight focused panel with brighter colors when focused, dimmer when not
        is_focused = self.focused_panel == 'stderr'
        if is_focused:
            border_style_stderr = "bright_red"
            title_style = "bold bright_red"
            focus_indicator = " [FOCUSED]"
        else:
            border_style_stderr = "dim red"
            title_style = "dim red"
            focus_indicator = " [Press Tab to focus]"
        
        # Add scroll mode indicator
        scroll_mode_indicator = ""
        if self.is_in_scroll_mode(job_id, 'stderr'):
            scroll_mode_indicator = " [SCROLL MODE - Press 'q' to exit]"
        
        stderr_panel = Panel(
            stderr_display,
            title=f"[{title_style}]STDERR[/{title_style}] (Job {job_id}){focus_indicator}{scroll_mode_indicator} | Tab to switch, ↑↓ to scroll, q to exit scroll",
            border_style=border_style_stderr,
            title_align="left"
        )
        output_layout["stderr"].update(stderr_panel)
        
        return output_layout
    
    def render(self) -> Layout:
        """
        Render the complete UI layout.
        
        Returns:
            The rendered Layout object
        """
        self.layout["header"].update(self._render_header())
        self.layout["status_panel"].update(self._render_status_panel())
        self.layout["output_panel"].update(self._render_output_panel())
        
        return self.layout
    
    def run_live(self, update_callback: Optional[callable] = None, keyboard_handler: Optional[callable] = None):
        """
        Run the UI in live update mode.
        
        Args:
            update_callback: Optional callback function called on each update cycle
            keyboard_handler: Optional function to check for keyboard input
        """
        with Live(self.layout, refresh_per_second=10, screen=True) as live:
            try:
                while True:
                    if update_callback:
                        update_callback()
                    
                    # Check for keyboard input if handler provided
                    if keyboard_handler:
                        try:
                            keyboard_handler()
                        except Exception:
                            pass
                    
                    live.update(self.render())
                    time.sleep(0.1)  # Update 10 times per second for smoother scrolling
            except KeyboardInterrupt:
                pass
    
    def scroll_stdout_up(self, lines: int = 1):
        """Scroll stdout up (show earlier content)."""
        if self.current_job_id and self.current_job_id in self.stdout_scroll_pos:
            self.stdout_scroll_pos[self.current_job_id] = max(0, self.stdout_scroll_pos[self.current_job_id] - lines)
            # Enter scroll mode when user manually scrolls
            if self.current_job_id:
                self.set_scroll_mode(self.current_job_id, 'stdout', True)
    
    def scroll_stdout_down(self, lines: int = 1):
        """Scroll stdout down (show later content)."""
        if self.current_job_id and self.current_job_id in self.stdout_scroll_pos:
            total_lines = len(self.stdout_lines.get(self.current_job_id, []))
            # Use cached max_lines_per_panel for consistency
            if self._cached_max_lines_per_panel is None:
                try:
                    terminal_height = self.console.height
                    available_height = terminal_height - 3 - 4
                    self._cached_max_lines_per_panel = max(5, available_height // 2 - 2)
                except Exception:
                    self._cached_max_lines_per_panel = 20
            max_lines_per_panel = self._cached_max_lines_per_panel
            max_scroll = max(0, total_lines - max_lines_per_panel)
            current_pos = self.stdout_scroll_pos[self.current_job_id]
            # Only scroll by the specified number of lines, don't jump to bottom
            new_pos = min(max_scroll, current_pos + lines)
            self.stdout_scroll_pos[self.current_job_id] = new_pos
            # Enter scroll mode when user manually scrolls - this prevents auto-scroll
            if self.current_job_id:
                self.set_scroll_mode(self.current_job_id, 'stdout', True)
                # Don't automatically exit scroll mode when reaching bottom
                # User must explicitly scroll to bottom or press 'q' to exit scroll mode
    
    def scroll_stderr_up(self, lines: int = 1):
        """Scroll stderr up (show earlier content)."""
        if self.current_job_id and self.current_job_id in self.stderr_scroll_pos:
            self.stderr_scroll_pos[self.current_job_id] = max(0, self.stderr_scroll_pos[self.current_job_id] - lines)
            # Enter scroll mode when user manually scrolls
            if self.current_job_id:
                self.set_scroll_mode(self.current_job_id, 'stderr', True)
    
    def scroll_stderr_down(self, lines: int = 1):
        """Scroll stderr down (show later content)."""
        if self.current_job_id and self.current_job_id in self.stderr_scroll_pos:
            total_lines = len(self.stderr_lines.get(self.current_job_id, []))
            # Use cached max_lines_per_panel for consistency
            if self._cached_max_lines_per_panel is None:
                try:
                    terminal_height = self.console.height
                    available_height = terminal_height - 3 - 4
                    self._cached_max_lines_per_panel = max(5, available_height // 2 - 2)
                except Exception:
                    self._cached_max_lines_per_panel = 20
            max_lines_per_panel = self._cached_max_lines_per_panel
            max_scroll = max(0, total_lines - max_lines_per_panel)
            current_pos = self.stderr_scroll_pos[self.current_job_id]
            # Only scroll by the specified number of lines, don't jump to bottom
            new_pos = min(max_scroll, current_pos + lines)
            self.stderr_scroll_pos[self.current_job_id] = new_pos
            # Enter scroll mode when user manually scrolls - this prevents auto-scroll
            if self.current_job_id:
                self.set_scroll_mode(self.current_job_id, 'stderr', True)
                # Don't automatically exit scroll mode when reaching bottom
                # User must explicitly scroll to bottom or press 'q' to exit scroll mode
    
    def scroll_to_bottom_stdout(self):
        """Scroll stdout to bottom (show latest content)."""
        if self.current_job_id:
            total_lines = len(self.stdout_lines.get(self.current_job_id, []))
            # Use cached max_lines_per_panel for consistency
            if self._cached_max_lines_per_panel is None:
                try:
                    terminal_height = self.console.height
                    available_height = terminal_height - 3 - 4
                    self._cached_max_lines_per_panel = max(5, available_height // 2 - 2)
                except Exception:
                    self._cached_max_lines_per_panel = 20
            max_lines_per_panel = self._cached_max_lines_per_panel
            self.stdout_scroll_pos[self.current_job_id] = max(0, total_lines - max_lines_per_panel)
            # Exit scroll mode when scrolling to bottom
            self.set_scroll_mode(self.current_job_id, 'stdout', False)
    
    def scroll_to_bottom_stderr(self):
        """Scroll stderr to bottom (show latest content)."""
        if self.current_job_id:
            total_lines = len(self.stderr_lines.get(self.current_job_id, []))
            # Use cached max_lines_per_panel for consistency
            if self._cached_max_lines_per_panel is None:
                try:
                    terminal_height = self.console.height
                    available_height = terminal_height - 3 - 4
                    self._cached_max_lines_per_panel = max(5, available_height // 2 - 2)
                except Exception:
                    self._cached_max_lines_per_panel = 20
            max_lines_per_panel = self._cached_max_lines_per_panel
            self.stderr_scroll_pos[self.current_job_id] = max(0, total_lines - max_lines_per_panel)
            # Exit scroll mode when scrolling to bottom
            self.set_scroll_mode(self.current_job_id, 'stderr', False)
    
    def switch_focus(self):
        """Switch focus between stdout and stderr panels."""
        if self.focused_panel == 'stdout':
            self.focused_panel = 'stderr'
        else:
            self.focused_panel = 'stdout'
    
    def scroll_up(self, lines: int = 1):
        """Scroll the currently focused panel up."""
        if self.focused_panel == 'stdout':
            self.scroll_stdout_up(lines)
        else:
            self.scroll_stderr_up(lines)
    
    def scroll_down(self, lines: int = 1):
        """Scroll the currently focused panel down."""
        if self.focused_panel == 'stdout':
            self.scroll_stdout_down(lines)
        else:
            self.scroll_stderr_down(lines)
    
    def scroll_to_bottom(self):
        """Scroll the currently focused panel to bottom."""
        if self.focused_panel == 'stdout':
            self.scroll_to_bottom_stdout()
        else:
            self.scroll_to_bottom_stderr()
    
    def scroll_to_top(self):
        """Scroll the currently focused panel to top."""
        if self.current_job_id:
            if self.focused_panel == 'stdout':
                self.stdout_scroll_pos[self.current_job_id] = 0
            else:
                self.stderr_scroll_pos[self.current_job_id] = 0
    
    def switch_to_next_job(self):
        """Switch to the next job in the list."""
        job_ids = sorted(self.job_data.keys())
        if not job_ids:
            return
        
        if self.current_job_id is None:
            self.current_job_id = job_ids[0]
        else:
            try:
                current_index = job_ids.index(self.current_job_id)
                next_index = (current_index + 1) % len(job_ids)
                self.current_job_id = job_ids[next_index]
            except ValueError:
                self.current_job_id = job_ids[0]
    
    def switch_to_previous_job(self):
        """Switch to the previous job in the list."""
        job_ids = sorted(self.job_data.keys())
        if not job_ids:
            return
        
        if self.current_job_id is None:
            self.current_job_id = job_ids[0]
        else:
            try:
                current_index = job_ids.index(self.current_job_id)
                prev_index = (current_index - 1) % len(job_ids)
                self.current_job_id = job_ids[prev_index]
            except ValueError:
                self.current_job_id = job_ids[0]
    
    def get_job_ids(self) -> List[int]:
        """Get list of all monitored job IDs."""
        return list(self.job_data.keys())
    
    def has_job(self, job_id: int) -> bool:
        """Check if a job is being monitored."""
        return job_id in self.job_data
    
    def remove_job(self, job_id: int):
        """Remove a job from the UI."""
        if job_id in self.job_data:
            del self.job_data[job_id]
        if job_id in self.log_data:
            del self.log_data[job_id]
        if job_id in self.stdout_scroll_pos:
            del self.stdout_scroll_pos[job_id]
        if job_id in self.stderr_scroll_pos:
            del self.stderr_scroll_pos[job_id]
        if job_id in self.stdout_lines:
            del self.stdout_lines[job_id]
        if job_id in self.stderr_lines:
            del self.stderr_lines[job_id]
        if job_id in self.scroll_mode:
            del self.scroll_mode[job_id]