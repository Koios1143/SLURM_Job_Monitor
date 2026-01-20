# SLURM Monitor (Rust)

A Rust CLI tool for real-time monitoring of SLURM jobs, providing a unified interface to view job status and live stdout/stderr output.

This is a Rust rewrite of the original Python SLURM Monitor.

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

- Rust 1.70+ (for building)
- SLURM workload manager installed and configured
- Access to SLURM commands: `sbatch`, `squeue`, `sacct`

## Building

```bash
# Install Rust (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Build release version
cd slurm-monitor-rs
cargo build --release

# The binary will be at target/release/slurm-monitor
```

## Installation

```bash
# Install directly
cargo install --path .

# Or copy the binary to your PATH
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

### Scrolling (affects focused panel)
- **Arrow keys (↑↓)**: Scroll through the focused panel (1 line at a time)
- **Page Up/Page Down**: Scroll by page (10 lines) in the focused panel
- **Home/End**: Jump to top/bottom of the focused panel
- **q**: Exit scroll mode and return to auto-scroll (or quit if not in scroll mode)

### Job Navigation
- **n**: Switch to next job
- **p**: Switch to previous job
- **d**: Remove current job from monitoring (does not cancel the job)

### Other
- **Ctrl+C**: Exit the monitor

## Architecture

```
src/
├── main.rs           # Entry point
├── cli.rs            # CLI definitions and command handlers
├── job_manager.rs    # SLURM job lifecycle management
├── status_monitor.rs # Multi-threaded status polling
├── log_tailer.rs     # File monitoring with notify
├── ui/
│   ├── mod.rs        # UI module exports
│   ├── app.rs        # Application state
│   └── render.rs     # Ratatui rendering
└── utils.rs          # SLURM command execution/parsing
```

## Dependencies

- `clap` - Command-line argument parsing
- `ratatui` - Terminal user interface
- `crossterm` - Cross-platform terminal manipulation
- `notify` - File system event monitoring
- `anyhow` / `thiserror` - Error handling
- `regex` - SLURM output parsing

## License

This project is provided as-is for use with SLURM workload managers.
