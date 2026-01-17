# SLURM Job Monitor

A Python CLI tool for real-time monitoring of SLURM jobs, providing unified interface to view job status and live stdout/stderr output.

## Features

- **Real-time job status monitoring**: Automatically polls SLURM to show job status (QUEUED, RUNNING, COMPLETED, FAILED)
- **Live stdout and stderr viewing**: Automatically monitors and displays output files as they are written
- **Scrollable output**: Use mouse scroll or arrow keys to navigate through output history with scroll mode support
- **Multi-job support**: Monitor multiple jobs simultaneously with easy switching
- **Auto-detect all jobs**: When no job IDs are provided, automatically monitors all visible jobs from `sacct`
- **Auto-discover new jobs**: When monitoring without specific job IDs, automatically discovers and adds new jobs to monitoring (every 10 seconds)
- **Focus preservation**: New jobs are added without disrupting your current view
- **Beautiful terminal UI**: Modern, color-coded interface using Rich library
- **Automatic file detection**: Automatically finds and monitors stdout/stderr files

## Installation

```bash
# Clone or navigate to the project directory
cd SLURM-tools

# Install in development mode
pip install -e .

# Or install dependencies directly
pip install -r requirements.txt
```

## Usage

### Submit and Monitor a Job

```bash
# Submit a job script and immediately start monitoring
slurm-monitor submit my_job.sh

# Submit without monitoring
slurm-monitor submit my_job.sh --no-watch
```

### Monitor Existing Jobs

```bash
# Monitor a single job
slurm-monitor watch 12345

# Monitor multiple jobs
slurm-monitor watch 12345 12346 12347

# Monitor all visible jobs from sacct and auto-discover new jobs (no job IDs needed)
slurm-monitor watch
```

Note: When no job IDs are provided, the monitor will automatically discover and add new jobs every 10 seconds without disrupting your current view.

### Other Commands

```bash
# List all tracked jobs
slurm-monitor list

# Stop tracking a job (does not cancel the job)
slurm-monitor stop 12345
```

## UI Controls

### Panel Focus (like tmux)
- **Tab**: Switch focus between STDOUT and STDERR panels
- The focused panel is highlighted with a brighter border and shows "[FOCUSED]" indicator
- Non-focused panels are dimmed for better visual distinction

### Scrolling (affects focused panel)
- **Arrow keys (↑↓)**: Scroll through the focused panel (1 line at a time)
- **Page Up/Page Down**: Scroll by page (10 lines) in the focused panel
- **Home/End**: Jump to top/bottom of the focused panel
- **q**: Exit scroll mode and return to auto-scroll (when in scroll mode)
- **Mouse wheel**: Scroll through the focused panel (may have limitations)

**Scroll Mode**: When you manually scroll (using arrow keys or mouse), the panel enters "scroll mode" which prevents automatic scrolling to the bottom. Press 'q' to exit scroll mode and return to auto-scroll behavior.

### Job Navigation
- **n**: Switch to next job (sorted by job ID, descending)
- **p**: Switch to previous job (sorted by job ID, descending)
- **d**: Remove current job from monitoring (does not cancel the job)

### Other
- **Ctrl+C**: Exit the monitor (does not cancel jobs)

Note: Keyboard controls work in most modern terminals. If keyboard shortcuts don't work, the output will still auto-scroll to show the latest content.

## How It Works

1. **Job Submission**: Uses `sbatch` to submit jobs and parses the job ID from output
2. **Status Monitoring**: Periodically queries `squeue` and `sacct` to get job status
3. **File Monitoring**: Uses `watchdog` library to monitor stdout/stderr files for changes
4. **Path Resolution**: Automatically finds output files using `sacct` or common naming patterns
5. **Auto Job Detection**: When no job IDs provided, uses `sacct` to get all visible jobs and monitors them
6. **Auto Job Discovery**: When monitoring without specific job IDs, periodically checks `sacct` for new jobs and automatically adds them to monitoring (every 10 seconds) while preserving your current focus

## Requirements

- Python 3.8+
- SLURM workload manager installed and configured
- Access to SLURM commands: `sbatch`, `squeue`, `sacct`
- Terminal with support for Rich library (most modern terminals)

## Troubleshooting

### Job output files not found

The tool tries multiple methods to find output files:
1. Uses `sacct` to get official paths
2. Checks current directory for `slurm-<job_id>.out` files
3. Checks for array job format `slurm-<job_id>_0.out`

If files are still not found, ensure:
- Job has started executing (files are created when job starts)
- You have read permissions for the output files
- Output files are in the expected location

### Status shows UNKNOWN

This usually means:
- Job ID doesn't exist
- SLURM commands are not available in PATH
- Permission issues accessing SLURM

### UI not displaying correctly

- Ensure your terminal supports Rich library features
- Try resizing your terminal window
- Check that your terminal supports colors and Unicode

## Development

The project structure:

```
slurm_monitor/
├── cli.py              # CLI entry point and command definitions
├── job_manager.py      # Job submission and status management
├── status_monitor.py   # Periodic status polling
├── log_tailer.py       # File monitoring for stdout/stderr
├── ui_renderer.py      # Rich-based terminal UI
└── utils.py            # Utility functions for SLURM commands
```

## License

This project is provided as-is for use with SLURM workload managers.
