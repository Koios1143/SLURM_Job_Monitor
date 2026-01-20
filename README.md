# SLURM Job Monitor

A CLI tool for real-time monitoring of SLURM jobs, providing a unified interface to view job status and live stdout/stderr output.

## Features

- **Real-time job status monitoring**: Automatically polls SLURM to show job status (QUEUED, RUNNING, COMPLETED, FAILED)
- **Live stdout and stderr viewing**: Automatically monitors and displays output files as they are written
- **Scrollable output**: Use arrow keys to navigate through output history with scroll mode support
- **Multi-job support**: Monitor multiple jobs simultaneously with easy switching
- **Auto-detect all jobs**: When no job IDs are provided, automatically monitors all visible jobs from `sacct`
- **Auto-discover new jobs**: When monitoring without specific job IDs, automatically discovers and adds new jobs to monitoring
- **Beautiful terminal UI**: Modern, color-coded interface using Ratatui
- **Single binary**: Easy deployment with no runtime dependencies

## Requirements

- SLURM workload manager installed and configured
- Access to SLURM commands: `sbatch`, `squeue`, `sacct`

### For Building from Source

- Rust 1.70+ (for building)

## Installation

### From Source (Recommended)

```bash
# Install Rust (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Clone and build
cd SLURM-tools/slurm-monitor-rs
cargo build --release

# Install to your PATH
cargo install --path .

# Or copy the binary manually
cp target/release/slurm-monitor ~/.local/bin/
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

# Monitor all visible jobs from sacct and auto-discover new jobs
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

### Panel Focus
- **Tab**: Switch focus between STDOUT and STDERR panels
- The focused panel is highlighted with a brighter border and shows "[FOCUSED]" indicator

### Scrolling (affects focused panel)
- **Arrow keys (↑↓)**: Scroll through the focused panel (1 line at a time)
- **Page Up/Page Down**: Scroll by page (10 lines) in the focused panel
- **Home/End**: Jump to top/bottom of the focused panel
- **q**: Exit scroll mode and return to auto-scroll (or quit if not in scroll mode)

**Scroll Mode**: When you manually scroll, the panel enters "scroll mode" which prevents automatic scrolling to the bottom. Press 'q' to exit scroll mode and return to auto-scroll behavior.

### Job Navigation
- **n**: Switch to next job (sorted by job ID, descending)
- **p**: Switch to previous job (sorted by job ID, descending)
- **d**: Remove current job from monitoring (does not cancel the job)

### Other
- **Ctrl+C**: Exit the monitor (does not cancel jobs)

## How It Works

1. **Job Submission**: Uses `sbatch` to submit jobs and parses the job ID from output
2. **Status Monitoring**: Periodically queries `squeue` and `sacct` to get job status
3. **File Monitoring**: Uses file system events to monitor stdout/stderr files for changes
4. **Path Resolution**: Automatically finds output files using `sacct` or common naming patterns
5. **Auto Job Detection**: When no job IDs provided, uses `sacct` to get all visible jobs
6. **Auto Job Discovery**: Periodically checks `sacct` for new jobs and automatically adds them to monitoring

## Project Structure

```
slurm-monitor-rs/
├── src/
│   ├── main.rs           # Entry point
│   ├── cli.rs            # CLI definitions and command handlers
│   ├── job_manager.rs    # SLURM job lifecycle management
│   ├── status_monitor.rs # Multi-threaded status polling
│   ├── log_tailer.rs     # File monitoring with notify
│   ├── ui/
│   │   ├── mod.rs        # UI module exports
│   │   ├── app.rs        # Application state
│   │   └── render.rs     # Ratatui rendering
│   └── utils.rs          # SLURM command execution/parsing
```

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

- Ensure your terminal supports modern features (colors, Unicode)
- Try resizing your terminal window
- If using tmux/screen, ensure proper terminal settings

## Python Version (Legacy)

A Python version is also available for systems where installing Rust is not feasible:

```bash
# Install Python version
cd SLURM-tools
pip install -e .

# Use with slurm-monitor-py command
slurm-monitor-py watch 12345
```

See [slurm_monitor/](./slurm_monitor/) for the Python implementation details.

## License

This project is provided as-is for use with SLURM workload managers.
