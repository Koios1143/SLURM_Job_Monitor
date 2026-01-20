//! Log Tailer for real-time monitoring of stdout/stderr files.

use notify::{Config, Event, RecommendedWatcher, RecursiveMode, Watcher};
use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread::{self, JoinHandle};
use std::time::Duration;

/// Log update message sent from the tailer thread to the UI.
#[derive(Debug, Clone)]
pub struct LogUpdate {
    pub label: String,
    pub content: String,
}

/// Command sent to the log tailer thread.
#[derive(Debug)]
pub enum TailerCommand {
    /// Add a file to monitor
    AddFile { label: String, path: PathBuf },
    /// Remove a file from monitoring
    RemoveFile { label: String },
    /// Stop the tailer
    Stop,
}

/// State for a monitored file
struct FileState {
    path: PathBuf,
    last_position: u64,
    initial_read_done: bool,
}

impl FileState {
    fn new(path: PathBuf) -> Self {
        Self {
            path,
            last_position: 0,
            initial_read_done: false,
        }
    }

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

    /// Read existing content from file.
    fn read_existing_content(&mut self) -> Option<String> {
        Self::debug_log(&format!("read_existing_content: path={} initial_read_done={}", self.path.display(), self.initial_read_done));
        if self.initial_read_done {
            return None;
        }

        let exists = self.path.exists();
        Self::debug_log(&format!("read_existing_content: path exists={}", exists));
        if !exists {
            self.initial_read_done = true;
            return None;
        }

        match File::open(&self.path) {
            Ok(mut file) => {
                let mut content = String::new();
                match file.read_to_string(&mut content) {
                    Ok(_) => {
                        Self::debug_log(&format!("read_existing_content: read {} bytes", content.len()));
                        if !content.is_empty() {
                            self.last_position = content.len() as u64;
                            self.initial_read_done = true;
                            return Some(content);
                        }
                    }
                    Err(e) => {
                        Self::debug_log(&format!("read_existing_content: read error: {}", e));
                    }
                }
                self.initial_read_done = true;
                None
            }
            Err(e) => {
                Self::debug_log(&format!("read_existing_content: open error: {}", e));
                self.initial_read_done = true;
                None
            }
        }
    }

    /// Read new content from the file since last read.
    fn read_new_content(&mut self) -> Option<String> {
        if !self.path.exists() {
            // Reset position if file was deleted
            self.last_position = 0;
            return None;
        }

        let metadata = match std::fs::metadata(&self.path) {
            Ok(m) => m,
            Err(_) => return None,
        };

        let current_size = metadata.len();

        // If file was truncated, reset position
        if current_size < self.last_position {
            self.last_position = 0;
        }

        // No new content
        if current_size == self.last_position {
            return None;
        }

        match File::open(&self.path) {
            Ok(mut file) => {
                if file.seek(SeekFrom::Start(self.last_position)).is_err() {
                    return None;
                }

                let mut content = String::new();
                if file.read_to_string(&mut content).is_ok() && !content.is_empty() {
                    self.last_position += content.len() as u64;
                    return Some(content);
                }
                None
            }
            Err(_) => None,
        }
    }
}

/// Monitors stdout/stderr files for real-time updates.
pub struct LogTailer {
    /// Polling interval for fallback mode
    poll_interval: Duration,
    /// Sender for commands to the tailer thread
    command_tx: Option<Sender<TailerCommand>>,
    /// Tailer thread handle
    thread_handle: Option<JoinHandle<()>>,
}

impl LogTailer {
    /// Create a new LogTailer.
    ///
    /// # Arguments
    /// * `poll_interval_secs` - Polling interval in seconds (default: 1.0)
    pub fn new(poll_interval_secs: f64) -> Self {
        Self {
            poll_interval: Duration::from_secs_f64(poll_interval_secs),
            command_tx: None,
            thread_handle: None,
        }
    }

    /// Start monitoring files.
    ///
    /// # Arguments
    /// * `update_tx` - Channel to send log updates
    pub fn start_monitoring(&mut self, update_tx: Sender<LogUpdate>) {
        // Stop any existing monitoring
        self.stop_monitoring();

        let (command_tx, command_rx) = mpsc::channel();
        self.command_tx = Some(command_tx);

        let poll_interval = self.poll_interval;

        // Start tailer thread
        let handle = thread::spawn(move || {
            Self::tailer_loop(command_rx, update_tx, poll_interval);
        });

        self.thread_handle = Some(handle);
    }

    /// Process a single command. Returns true if the loop should stop.
    fn process_command(
        cmd: TailerCommand,
        files: &mut HashMap<String, FileState>,
        watcher: &mut Option<RecommendedWatcher>,
        update_tx: &Sender<LogUpdate>,
    ) -> bool {
        match cmd {
            TailerCommand::AddFile { label, path } => {
                FileState::debug_log(&format!("process_command: AddFile label={} path={}", label, path.display()));
                let mut state = FileState::new(path.clone());

                // Read existing content
                if let Some(content) = state.read_existing_content() {
                    FileState::debug_log(&format!("read_existing_content returned {} bytes for {}", content.len(), label));
                    let send_result = update_tx.send(LogUpdate {
                        label: label.clone(),
                        content,
                    });
                    FileState::debug_log(&format!("update_tx.send result: {:?}", send_result.is_ok()));
                } else {
                    FileState::debug_log(&format!("read_existing_content returned None for {}", label));
                }

                // Set up watcher for the directory if possible
                if let Some(ref mut w) = watcher {
                    if let Some(parent) = path.parent() {
                        let _ = w.watch(parent, RecursiveMode::NonRecursive);
                    }
                }

                files.insert(label, state);
                false
            }
            TailerCommand::RemoveFile { label } => {
                files.remove(&label);
                false
            }
            TailerCommand::Stop => true,
        }
    }

    /// Tailer loop running in a separate thread.
    fn tailer_loop(
        command_rx: Receiver<TailerCommand>,
        update_tx: Sender<LogUpdate>,
        poll_interval: Duration,
    ) {
        let mut files: HashMap<String, FileState> = HashMap::new();
        let mut watcher: Option<RecommendedWatcher> = None;
        let (notify_tx, notify_rx) = mpsc::channel();

        // Try to set up file watcher
        if let Ok(w) = RecommendedWatcher::new(
            move |res: Result<Event, notify::Error>| {
                if let Ok(event) = res {
                    let _ = notify_tx.send(event);
                }
            },
            Config::default(),
        ) {
            watcher = Some(w);
        }

        loop {
            // Process all pending commands
            while let Ok(cmd) = command_rx.try_recv() {
                if Self::process_command(cmd, &mut files, &mut watcher, &update_tx) {
                    return;
                }
            }

            // Check for file events from watcher
            while let Ok(event) = notify_rx.try_recv() {
                for (label, state) in files.iter_mut() {
                    if event.paths.iter().any(|p| p == &state.path) {
                        if let Some(content) = state.read_new_content() {
                            let _ = update_tx.send(LogUpdate {
                                label: label.clone(),
                                content,
                            });
                        }
                    }
                }
            }

            // Fallback: poll all files for changes
            for (label, state) in files.iter_mut() {
                if let Some(content) = state.read_new_content() {
                    if update_tx
                        .send(LogUpdate {
                            label: label.clone(),
                            content,
                        })
                        .is_err()
                    {
                        // Receiver dropped
                        return;
                    }
                }
            }

            // Wait for poll interval, processing any commands that arrive
            let check_interval = Duration::from_millis(100);
            let mut elapsed = Duration::ZERO;
            while elapsed < poll_interval {
                // Process ALL pending commands during wait period
                while let Ok(cmd) = command_rx.try_recv() {
                    if Self::process_command(cmd, &mut files, &mut watcher, &update_tx) {
                        return;
                    }
                }
                thread::sleep(check_interval);
                elapsed += check_interval;
            }
        }
    }

    /// Stop monitoring all files.
    pub fn stop_monitoring(&mut self) {
        if let Some(tx) = self.command_tx.take() {
            let _ = tx.send(TailerCommand::Stop);
        }

        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }
    }

    /// Add a file to monitor.
    pub fn add_file(&self, label: &str, path: &Path) {
        FileState::debug_log(&format!("add_file called: label={} path={} has_tx={}", label, path.display(), self.command_tx.is_some()));
        if let Some(ref tx) = self.command_tx {
            let result = tx.send(TailerCommand::AddFile {
                label: label.to_string(),
                path: path.to_path_buf(),
            });
            FileState::debug_log(&format!("add_file send result: {:?}", result.is_ok()));
        }
    }

    /// Remove a file from monitoring.
    pub fn remove_file(&self, label: &str) {
        if let Some(ref tx) = self.command_tx {
            let _ = tx.send(TailerCommand::RemoveFile {
                label: label.to_string(),
            });
        }
    }
}

impl Drop for LogTailer {
    fn drop(&mut self) {
        self.stop_monitoring();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_file_state_read_existing() {
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, "Hello, World!").unwrap();
        temp_file.flush().unwrap();

        let mut state = FileState::new(temp_file.path().to_path_buf());
        let content = state.read_existing_content();
        
        assert!(content.is_some());
        assert!(content.unwrap().contains("Hello, World!"));
        assert!(state.initial_read_done);
    }

    #[test]
    fn test_file_state_read_new() {
        let mut temp_file = NamedTempFile::new().unwrap();
        writeln!(temp_file, "Initial").unwrap();
        temp_file.flush().unwrap();

        let mut state = FileState::new(temp_file.path().to_path_buf());
        state.read_existing_content(); // Read initial content

        // Write more content
        writeln!(temp_file, "New content").unwrap();
        temp_file.flush().unwrap();

        let new_content = state.read_new_content();
        assert!(new_content.is_some());
        assert!(new_content.unwrap().contains("New content"));
    }
}
