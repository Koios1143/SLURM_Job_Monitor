//! Application state management for the TUI.

use crate::job_manager::JobInfo;
use crate::utils::JobStatus;
use ratatui::layout::{Constraint, Direction, Layout, Rect};
use std::collections::{HashMap, HashSet};

/// Which panel is currently focused
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FocusedPanel {
    Stdout,
    Stderr,
}

impl FocusedPanel {
    pub fn toggle(&mut self) {
        *self = match self {
            FocusedPanel::Stdout => FocusedPanel::Stderr,
            FocusedPanel::Stderr => FocusedPanel::Stdout,
        };
    }
}

/// Data for a single job
#[derive(Debug, Clone, Default)]
pub struct JobData {
    pub status: JobStatus,
    pub info: JobInfo,
    pub stdout: String,
    pub stderr: String,
    pub stdout_lines: Vec<String>,
    pub stderr_lines: Vec<String>,
    pub stdout_scroll: usize,
    pub stderr_scroll: usize,
    pub stdout_scroll_mode: bool,
    pub stderr_scroll_mode: bool,
}

impl JobData {
    pub fn new(job_id: u64) -> Self {
        Self {
            status: JobStatus::Unknown,
            info: JobInfo {
                job_id,
                ..Default::default()
            },
            ..Default::default()
        }
    }

    /// Process log content to handle carriage returns (progress bars).
    /// Simulates terminal behavior: \r returns to line start, overwriting previous content.
    fn process_log_content(content: &str) -> Vec<String> {
        let mut lines: Vec<String> = Vec::new();
        let mut current_line = String::new();

        for ch in content.chars() {
            match ch {
                '\r' => {
                    // Carriage return: reset to beginning of current line (don't push yet)
                    current_line.clear();
                }
                '\n' => {
                    // Newline: push current line and start fresh
                    lines.push(current_line.clone());
                    current_line.clear();
                }
                _ => {
                    current_line.push(ch);
                }
            }
        }

        // Don't forget any trailing content without a newline
        if !current_line.is_empty() {
            lines.push(current_line);
        }

        lines
    }

    /// Update stdout content
    pub fn append_stdout(&mut self, content: &str, max_visible_lines: usize) {
        self.stdout.push_str(content);
        self.stdout_lines = Self::process_log_content(&self.stdout);

        // Auto-scroll to bottom if not in scroll mode
        if !self.stdout_scroll_mode {
            self.scroll_stdout_to_bottom(max_visible_lines);
        }
    }

    /// Update stderr content
    pub fn append_stderr(&mut self, content: &str, max_visible_lines: usize) {
        self.stderr.push_str(content);
        self.stderr_lines = Self::process_log_content(&self.stderr);

        // Auto-scroll to bottom if not in scroll mode
        if !self.stderr_scroll_mode {
            self.scroll_stderr_to_bottom(max_visible_lines);
        }
    }

    /// Scroll stdout to bottom
    pub fn scroll_stdout_to_bottom(&mut self, max_visible_lines: usize) {
        let total = self.stdout_lines.len();
        self.stdout_scroll = total.saturating_sub(max_visible_lines);
        self.stdout_scroll_mode = false;
    }

    /// Scroll stderr to bottom
    pub fn scroll_stderr_to_bottom(&mut self, max_visible_lines: usize) {
        let total = self.stderr_lines.len();
        self.stderr_scroll = total.saturating_sub(max_visible_lines);
        self.stderr_scroll_mode = false;
    }
}

/// Main application state
pub struct App {
    /// All job data
    pub jobs: HashMap<u64, JobData>,
    /// Currently selected job ID
    pub current_job_id: Option<u64>,
    /// Which panel is focused
    pub focused_panel: FocusedPanel,
    /// Whether the app should quit
    pub should_quit: bool,
    /// Max visible lines per panel (cached, for backwards compatibility)
    pub max_visible_lines: usize,
    /// Actual stdout panel inner height (set from render layout)
    pub stdout_panel_height: usize,
    /// Actual stderr panel inner height (set from render layout)
    pub stderr_panel_height: usize,
    /// Auto-discover new jobs
    pub auto_discover: bool,
    /// Jobs that have been explicitly deleted by the user (to prevent re-adding via auto-discovery)
    pub deleted_jobs: HashSet<u64>,
}

impl App {
    /// Create a new App instance.
    pub fn new() -> Self {
        Self {
            jobs: HashMap::new(),
            current_job_id: None,
            focused_panel: FocusedPanel::Stdout,
            should_quit: false,
            max_visible_lines: 20, // Default, will be updated based on terminal size
            stdout_panel_height: 20, // Default, will be updated from actual render layout
            stderr_panel_height: 20, // Default, will be updated from actual render layout
            auto_discover: false,
            deleted_jobs: HashSet::new(),
        }
    }

    /// Add a job to track.
    pub fn add_job(&mut self, job_id: u64) {
        if !self.jobs.contains_key(&job_id) {
            self.jobs.insert(job_id, JobData::new(job_id));
        }
        if self.current_job_id.is_none() {
            self.current_job_id = Some(job_id);
        }
    }

    /// Remove a job from tracking.
    pub fn remove_job(&mut self, job_id: u64) {
        self.jobs.remove(&job_id);
        // Track deleted jobs to prevent re-adding via auto-discovery
        self.deleted_jobs.insert(job_id);
        if self.current_job_id == Some(job_id) {
            self.current_job_id = self.get_sorted_job_ids().first().copied();
        }
    }

    /// Get sorted job IDs (descending order).
    pub fn get_sorted_job_ids(&self) -> Vec<u64> {
        let mut ids: Vec<u64> = self.jobs.keys().copied().collect();
        ids.sort_unstable_by(|a, b| b.cmp(a));
        ids
    }

    /// Update job status.
    pub fn update_job_status(&mut self, job_id: u64, status: JobStatus, info: JobInfo) {
        if let Some(job) = self.jobs.get_mut(&job_id) {
            job.status = status;
            job.info = info;
        } else {
            let mut job_data = JobData::new(job_id);
            job_data.status = status;
            job_data.info = info;
            self.jobs.insert(job_id, job_data);
            if self.current_job_id.is_none() {
                self.current_job_id = Some(job_id);
            }
        }
    }

    /// Update log content.
    pub fn update_log(&mut self, job_id: u64, log_type: &str, content: &str) {
        if let Some(job) = self.jobs.get_mut(&job_id) {
            match log_type {
                "stdout" => job.append_stdout(content, self.stdout_panel_height),
                "stderr" => job.append_stderr(content, self.stderr_panel_height),
                _ => {}
            }
        }
    }

    /// Switch focus between panels.
    pub fn switch_focus(&mut self) {
        self.focused_panel.toggle();
    }

    /// Switch to next job.
    pub fn next_job(&mut self) {
        let ids = self.get_sorted_job_ids();
        if ids.is_empty() {
            return;
        }

        self.current_job_id = match self.current_job_id {
            Some(current) => {
                let idx = ids.iter().position(|&id| id == current).unwrap_or(0);
                Some(ids[(idx + 1) % ids.len()])
            }
            None => Some(ids[0]),
        };
    }

    /// Switch to previous job.
    pub fn prev_job(&mut self) {
        let ids = self.get_sorted_job_ids();
        if ids.is_empty() {
            return;
        }

        self.current_job_id = match self.current_job_id {
            Some(current) => {
                let idx = ids.iter().position(|&id| id == current).unwrap_or(0);
                Some(ids[(idx + ids.len() - 1) % ids.len()])
            }
            None => Some(ids[0]),
        };
    }

    /// Scroll the focused panel up.
    pub fn scroll_up(&mut self, lines: usize) {
        if let Some(job_id) = self.current_job_id {
            if let Some(job) = self.jobs.get_mut(&job_id) {
                match self.focused_panel {
                    FocusedPanel::Stdout => {
                        let visible_lines = self.stdout_panel_height;
                        let max_scroll = job.stdout_lines.len().saturating_sub(visible_lines);
                        if max_scroll == 0 {
                            // Not enough content to scroll
                            return;
                        }
                        let old_scroll = job.stdout_scroll;
                        job.stdout_scroll = job.stdout_scroll.saturating_sub(lines);
                        if job.stdout_scroll != old_scroll {
                            job.stdout_scroll_mode = true;
                        }
                    }
                    FocusedPanel::Stderr => {
                        let visible_lines = self.stderr_panel_height;
                        let max_scroll = job.stderr_lines.len().saturating_sub(visible_lines);
                        if max_scroll == 0 {
                            // Not enough content to scroll
                            return;
                        }
                        let old_scroll = job.stderr_scroll;
                        job.stderr_scroll = job.stderr_scroll.saturating_sub(lines);
                        if job.stderr_scroll != old_scroll {
                            job.stderr_scroll_mode = true;
                        }
                    }
                }
            }
        }
    }

    /// Scroll the focused panel down.
    pub fn scroll_down(&mut self, lines: usize) {
        if let Some(job_id) = self.current_job_id {
            if let Some(job) = self.jobs.get_mut(&job_id) {
                match self.focused_panel {
                    FocusedPanel::Stdout => {
                        let visible_lines = self.stdout_panel_height;
                        let max_scroll = job.stdout_lines.len().saturating_sub(visible_lines);
                        if max_scroll == 0 {
                            // Not enough content to scroll
                            return;
                        }
                        let old_scroll = job.stdout_scroll;
                        job.stdout_scroll = (job.stdout_scroll + lines).min(max_scroll);
                        if job.stdout_scroll != old_scroll {
                            job.stdout_scroll_mode = true;
                        } else if job.stdout_scroll == max_scroll {
                            // Already at bottom - exit scroll mode to resume auto-scroll
                            job.stdout_scroll_mode = false;
                        }
                    }
                    FocusedPanel::Stderr => {
                        let visible_lines = self.stderr_panel_height;
                        let max_scroll = job.stderr_lines.len().saturating_sub(visible_lines);
                        if max_scroll == 0 {
                            // Not enough content to scroll
                            return;
                        }
                        let old_scroll = job.stderr_scroll;
                        job.stderr_scroll = (job.stderr_scroll + lines).min(max_scroll);
                        if job.stderr_scroll != old_scroll {
                            job.stderr_scroll_mode = true;
                        } else if job.stderr_scroll == max_scroll {
                            // Already at bottom - exit scroll mode to resume auto-scroll
                            job.stderr_scroll_mode = false;
                        }
                    }
                }
            }
        }
    }

    /// Scroll to top.
    pub fn scroll_to_top(&mut self) {
        if let Some(job_id) = self.current_job_id {
            if let Some(job) = self.jobs.get_mut(&job_id) {
                match self.focused_panel {
                    FocusedPanel::Stdout => {
                        job.stdout_scroll = 0;
                        job.stdout_scroll_mode = true;
                    }
                    FocusedPanel::Stderr => {
                        job.stderr_scroll = 0;
                        job.stderr_scroll_mode = true;
                    }
                }
            }
        }
    }

    /// Scroll to bottom (exit scroll mode).
    pub fn scroll_to_bottom(&mut self) {
        if let Some(job_id) = self.current_job_id {
            if let Some(job) = self.jobs.get_mut(&job_id) {
                match self.focused_panel {
                    FocusedPanel::Stdout => {
                        job.scroll_stdout_to_bottom(self.stdout_panel_height);
                    }
                    FocusedPanel::Stderr => {
                        job.scroll_stderr_to_bottom(self.stderr_panel_height);
                    }
                }
            }
        }
    }

    /// Exit scroll mode for the focused panel.
    pub fn exit_scroll_mode(&mut self) {
        self.scroll_to_bottom();
    }

    /// Remove the current job.
    pub fn remove_current_job(&mut self) {
        if let Some(job_id) = self.current_job_id {
            self.remove_job(job_id);
        }
    }

    /// Update panel heights based on terminal size using exact same Layout as render.rs.
    /// This ensures scroll calculations match what's actually rendered.
    pub fn update_panel_heights(&mut self, frame_area: Rect) {
        // Replicate exact layout from render.rs:
        // 1. Main vertical split: header (3 lines) + body
        let main_chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([
                Constraint::Length(3), // Header
                Constraint::Min(0),    // Body
            ])
            .split(frame_area);

        let body_area = main_chunks[1];

        // 2. Body horizontal split: 35% status + 65% output
        let body_chunks = Layout::default()
            .direction(Direction::Horizontal)
            .constraints([
                Constraint::Percentage(35), // Status panel
                Constraint::Percentage(65), // Output panel
            ])
            .split(body_area);

        let output_area = body_chunks[1];

        // 3. Output vertical split: 50% stdout + 50% stderr
        let output_chunks = Layout::default()
            .direction(Direction::Vertical)
            .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
            .split(output_area);

        // 4. Inner height = panel height - 2 (for borders)
        self.stdout_panel_height = output_chunks[0].height.saturating_sub(2).max(1) as usize;
        self.stderr_panel_height = output_chunks[1].height.saturating_sub(2).max(1) as usize;

        // Also update max_visible_lines for backwards compatibility
        self.max_visible_lines = self.stdout_panel_height;
    }

    /// Check if current job is in scroll mode.
    pub fn is_in_scroll_mode(&self) -> bool {
        if let Some(job_id) = self.current_job_id {
            if let Some(job) = self.jobs.get(&job_id) {
                return match self.focused_panel {
                    FocusedPanel::Stdout => job.stdout_scroll_mode,
                    FocusedPanel::Stderr => job.stderr_scroll_mode,
                };
            }
        }
        false
    }
}

impl Default for App {
    fn default() -> Self {
        Self::new()
    }
}

impl Default for JobStatus {
    fn default() -> Self {
        JobStatus::Unknown
    }
}
