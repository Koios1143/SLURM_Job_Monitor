//! CLI entry point and command definitions.

use crate::job_manager::JobManager;

/// Write debug message to file
fn debug_log(msg: &str) {
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open("/tmp/slurm_monitor_debug.log")
    {
        let _ = writeln!(f, "{}", msg);
    }
}
use crate::log_tailer::{LogTailer, LogUpdate};
use crate::status_monitor::{StatusMonitor, StatusUpdate};
use crate::ui::{self, App};
use crate::utils::get_all_job_ids_from_sacct;
use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use crossterm::{
    cursor::{Hide, Show},
    event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind},
    execute, queue,
    terminal::{
        disable_raw_mode, enable_raw_mode, BeginSynchronizedUpdate, EndSynchronizedUpdate,
        EnterAlternateScreen, LeaveAlternateScreen,
    },
};
use ratatui::prelude::*;
use std::io::{self, stdout};
use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// SLURM Job Monitor - Real-time monitoring tool for SLURM jobs.
#[derive(Parser)]
#[command(name = "slurm-monitor")]
#[command(version = "0.1.0")]
#[command(about = "Real-time monitoring tool for SLURM jobs")]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand)]
pub enum Commands {
    /// Submit a SLURM job script and optionally start monitoring
    Submit {
        /// Path to the SLURM batch script
        script: PathBuf,
        /// Do not start monitoring after submission
        #[arg(long)]
        no_watch: bool,
    },
    /// Monitor one or more existing SLURM jobs
    Watch {
        /// Job IDs to monitor (if none provided, monitors all visible jobs)
        job_ids: Vec<u64>,
    },
    /// List all currently tracked jobs
    List,
    /// Stop monitoring a specific job (does not cancel the job)
    Stop {
        /// Job ID to stop monitoring
        job_id: u64,
    },
}

/// Handle the submit command.
pub fn handle_submit(script: &PathBuf, no_watch: bool) -> Result<()> {
    let mut job_manager = JobManager::new();
    let job_id = job_manager
        .submit_job(script, &[])
        .context("Failed to submit job")?;

    println!("Submitted job {}", job_id);

    if !no_watch {
        println!("Starting monitor...");
        run_monitor(vec![job_id], false)?;
    } else {
        println!(
            "Job {} submitted. Use 'slurm-monitor watch {}' to monitor it.",
            job_id, job_id
        );
    }

    Ok(())
}

/// Handle the watch command.
pub fn handle_watch(job_ids: Vec<u64>) -> Result<()> {
    let (job_ids, auto_discover) = if job_ids.is_empty() {
        println!("No job IDs provided. Fetching all visible jobs from sacct...");
        let all_jobs = get_all_job_ids_from_sacct();
        if all_jobs.is_empty() {
            println!("No jobs found in sacct. Will monitor for new jobs...");
        } else {
            println!(
                "Found {} job(s): {}",
                all_jobs.len(),
                all_jobs
                    .iter()
                    .map(|id| id.to_string())
                    .collect::<Vec<_>>()
                    .join(", ")
            );
        }
        println!("Auto-discovery enabled: new jobs will be automatically added to monitoring.");
        (all_jobs, true)
    } else {
        (job_ids, false)
    };

    run_monitor(job_ids, auto_discover)?;
    Ok(())
}

/// Handle the list command.
pub fn handle_list() -> Result<()> {
    let job_manager = JobManager::new();
    let all_jobs = get_all_job_ids_from_sacct();

    if all_jobs.is_empty() {
        println!("No tracked jobs");
        return Ok(());
    }

    println!("Tracked jobs:");
    for job_id in all_jobs {
        let status = job_manager.get_job_status(job_id);
        let info = job_manager.get_job_info(job_id);
        let job_name = if info.job_name.is_empty() {
            "N/A".to_string()
        } else {
            info.job_name
        };
        println!("  {}: {} - {}", job_id, status, job_name);
    }

    Ok(())
}

/// Handle the stop command.
pub fn handle_stop(job_id: u64) -> Result<()> {
    println!("Stopped tracking job {}", job_id);
    println!("Note: This command is informational only in the Rust version.");
    println!("The job continues running on SLURM.");
    Ok(())
}

/// Run the monitor UI.
fn run_monitor(initial_job_ids: Vec<u64>, auto_discover: bool) -> Result<()> {
    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture, Hide)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // Create app state
    let mut app = App::new();
    app.auto_discover = auto_discover;

    // Initialize jobs
    for &job_id in &initial_job_ids {
        app.add_job(job_id);
    }

    // Create channels for updates
    let (status_tx, status_rx) = mpsc::channel();
    let (log_tx, log_rx) = mpsc::channel();

    // Create job manager
    let job_manager = Arc::new(Mutex::new(JobManager::new()));
    for &job_id in &initial_job_ids {
        job_manager.lock().unwrap().add_tracked_job(job_id);
    }

    // Start status monitor
    let mut status_monitor = StatusMonitor::new(Arc::clone(&job_manager), 3.0);
    status_monitor.start_monitoring(initial_job_ids.clone(), status_tx);

    // Start log tailer
    let mut log_tailer = LogTailer::new(1.0);
    log_tailer.start_monitoring(log_tx.clone());

    // Add initial log files to monitor
    for &job_id in &initial_job_ids {
        let info = job_manager.lock().unwrap().get_job_info(job_id);
        if !info.stdout_path.as_os_str().is_empty() {
            log_tailer.add_file(&format!("stdout_{}", job_id), &info.stdout_path);
        }
        if !info.stderr_path.as_os_str().is_empty() {
            log_tailer.add_file(&format!("stderr_{}", job_id), &info.stderr_path);
        }
    }

    // Run event loop
    let result = run_event_loop(
        &mut terminal,
        &mut app,
        status_rx,
        log_rx,
        &job_manager,
        &log_tailer,
        &status_monitor,
    );

    // Cleanup
    status_monitor.stop_monitoring();
    log_tailer.stop_monitoring();
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture,
        Show
    )?;

    result
}

/// Main event loop.
fn run_event_loop(
    terminal: &mut Terminal<CrosstermBackend<io::Stdout>>,
    app: &mut App,
    status_rx: Receiver<StatusUpdate>,
    log_rx: Receiver<LogUpdate>,
    job_manager: &Arc<Mutex<JobManager>>,
    log_tailer: &LogTailer,
    status_monitor: &StatusMonitor,
) -> Result<()> {
    let tick_rate = Duration::from_millis(100);
    let mut last_tick = Instant::now();
    let mut last_discovery = Instant::now();
    let discovery_interval = Duration::from_secs(10);

    loop {
        // Update panel heights using actual terminal size and layout calculations
        let size = terminal.size()?;
        let frame_area = ratatui::layout::Rect::new(0, 0, size.width, size.height);
        app.update_panel_heights(frame_area);

        // Draw UI with synchronized update (prevents flicker in tmux and other terminals)
        {
            let backend = terminal.backend_mut();
            queue!(backend, BeginSynchronizedUpdate)?;
        }
        terminal.draw(|frame| {
            ui::render(frame, app);
        })?;
        {
            let backend = terminal.backend_mut();
            queue!(backend, EndSynchronizedUpdate)?;
            std::io::Write::flush(backend)?;
        }

        // Handle status updates (non-blocking)
        while let Ok(update) = status_rx.try_recv() {
            app.update_job_status(update.job_id, update.status, update.info.clone());

            // Add log files if we have paths now
            if !update.info.stdout_path.as_os_str().is_empty() {
                log_tailer.add_file(
                    &format!("stdout_{}", update.job_id),
                    &update.info.stdout_path,
                );
            }
            if !update.info.stderr_path.as_os_str().is_empty() {
                log_tailer.add_file(
                    &format!("stderr_{}", update.job_id),
                    &update.info.stderr_path,
                );
            }
        }

        // Handle log updates (non-blocking)
        while let Ok(update) = log_rx.try_recv() {
            debug_log(&format!("cli: received LogUpdate label={} content_len={}", update.label, update.content.len()));
            // Parse label to get job_id and log type
            if let Some((log_type, job_id_str)) = update.label.split_once('_') {
                if let Ok(job_id) = job_id_str.parse::<u64>() {
                    debug_log(&format!("cli: updating log for job {} type {}", job_id, log_type));
                    app.update_log(job_id, log_type, &update.content);
                }
            }
        }

        // Auto-discover new jobs
        if app.auto_discover && last_discovery.elapsed() >= discovery_interval {
            last_discovery = Instant::now();
            let current_jobs: Vec<u64> = app.jobs.keys().copied().collect();
            let all_jobs = get_all_job_ids_from_sacct();

            for job_id in all_jobs {
                if !current_jobs.contains(&job_id) {
                    app.add_job(job_id);
                    job_manager.lock().unwrap().add_tracked_job(job_id);
                    status_monitor.add_job_to_monitor(job_id);
                }
            }
        }

        // Handle input events
        let timeout = tick_rate
            .checked_sub(last_tick.elapsed())
            .unwrap_or_else(|| Duration::from_secs(0));

        if crossterm::event::poll(timeout)? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    match key.code {
                        KeyCode::Char('q') => {
                            if app.is_in_scroll_mode() {
                                app.exit_scroll_mode();
                            } else {
                                app.should_quit = true;
                            }
                        }
                        KeyCode::Char('c') if key.modifiers.contains(event::KeyModifiers::CONTROL) => {
                            app.should_quit = true;
                        }
                        KeyCode::Tab => {
                            app.switch_focus();
                        }
                        KeyCode::Char('n') => {
                            app.prev_job();
                        }
                        KeyCode::Char('p') => {
                            app.next_job();
                        }
                        KeyCode::Char('d') => {
                            if let Some(job_id) = app.current_job_id {
                                status_monitor.remove_job_from_monitor(job_id);
                                log_tailer.remove_file(&format!("stdout_{}", job_id));
                                log_tailer.remove_file(&format!("stderr_{}", job_id));
                                app.remove_current_job();
                            }
                        }
                        KeyCode::Up => {
                            app.scroll_up(1);
                        }
                        KeyCode::Down => {
                            app.scroll_down(1);
                        }
                        KeyCode::PageUp => {
                            app.scroll_up(10);
                        }
                        KeyCode::PageDown => {
                            app.scroll_down(10);
                        }
                        KeyCode::Home => {
                            app.scroll_to_top();
                        }
                        KeyCode::End => {
                            app.scroll_to_bottom();
                        }
                        _ => {}
                    }
                }
            }
        }

        if last_tick.elapsed() >= tick_rate {
            last_tick = Instant::now();
        }

        if app.should_quit {
            break;
        }
    }

    Ok(())
}
