//! Status Monitor for polling SLURM job status.

use crate::job_manager::{JobInfo, JobManager};
use crate::utils::JobStatus;
use std::collections::HashMap;
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

/// Status update message sent from the monitor thread to the UI.
#[derive(Debug, Clone)]
pub struct StatusUpdate {
    pub job_id: u64,
    pub status: JobStatus,
    pub info: JobInfo,
}

/// Command sent to the monitor thread.
#[derive(Debug)]
pub enum MonitorCommand {
    /// Add a job to monitor
    AddJob(u64),
    /// Remove a job from monitoring
    RemoveJob(u64),
    /// Stop the monitor
    Stop,
}

/// Monitors SLURM job status with periodic polling.
pub struct StatusMonitor {
    /// Polling interval in seconds
    poll_interval: Duration,
    /// Sender for commands to the monitor thread
    command_tx: Option<Sender<MonitorCommand>>,
    /// Monitor thread handle
    thread_handle: Option<JoinHandle<()>>,
    /// Shared job manager
    job_manager: Arc<Mutex<JobManager>>,
    /// Current status cache
    current_statuses: Arc<Mutex<HashMap<u64, StatusUpdate>>>,
}

impl StatusMonitor {
    /// Create a new StatusMonitor.
    ///
    /// # Arguments
    /// * `job_manager` - Shared JobManager instance
    /// * `poll_interval_secs` - Polling interval in seconds (default: 3.0)
    pub fn new(job_manager: Arc<Mutex<JobManager>>, poll_interval_secs: f64) -> Self {
        Self {
            poll_interval: Duration::from_secs_f64(poll_interval_secs),
            command_tx: None,
            thread_handle: None,
            job_manager,
            current_statuses: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Start monitoring jobs.
    ///
    /// # Arguments
    /// * `job_ids` - List of job IDs to monitor
    /// * `update_tx` - Channel to send status updates
    pub fn start_monitoring(&mut self, job_ids: Vec<u64>, update_tx: Sender<StatusUpdate>) {
        // Stop any existing monitoring
        self.stop_monitoring();

        let (command_tx, command_rx) = mpsc::channel();
        self.command_tx = Some(command_tx);

        // Initialize statuses
        {
            let mut statuses = self.current_statuses.lock().unwrap();
            for &job_id in &job_ids {
                statuses.insert(
                    job_id,
                    StatusUpdate {
                        job_id,
                        status: JobStatus::Unknown,
                        info: JobInfo {
                            job_id,
                            ..Default::default()
                        },
                    },
                );
            }
        }

        let job_manager = Arc::clone(&self.job_manager);
        let current_statuses = Arc::clone(&self.current_statuses);
        let poll_interval = self.poll_interval;
        let initial_jobs = job_ids.clone();

        // Start monitor thread
        let handle = thread::spawn(move || {
            Self::monitor_loop(
                command_rx,
                update_tx,
                job_manager,
                current_statuses,
                poll_interval,
                initial_jobs,
            );
        });

        self.thread_handle = Some(handle);
    }

    /// Monitor loop running in a separate thread.
    fn monitor_loop(
        command_rx: Receiver<MonitorCommand>,
        update_tx: Sender<StatusUpdate>,
        job_manager: Arc<Mutex<JobManager>>,
        current_statuses: Arc<Mutex<HashMap<u64, StatusUpdate>>>,
        poll_interval: Duration,
        initial_jobs: Vec<u64>,
    ) {
        let mut monitored_jobs: Vec<u64> = initial_jobs;

        loop {
            // Check for commands (non-blocking)
            while let Ok(cmd) = command_rx.try_recv() {
                match cmd {
                    MonitorCommand::AddJob(job_id) => {
                        if !monitored_jobs.contains(&job_id) {
                            monitored_jobs.push(job_id);
                        }
                    }
                    MonitorCommand::RemoveJob(job_id) => {
                        monitored_jobs.retain(|&id| id != job_id);
                        current_statuses.lock().unwrap().remove(&job_id);
                    }
                    MonitorCommand::Stop => {
                        return;
                    }
                }
            }

            // Poll each job's status
            for &job_id in &monitored_jobs {
                let (status, info) = {
                    let manager = job_manager.lock().unwrap();
                    let status = manager.get_job_status(job_id);
                    let info = manager.get_job_info(job_id);
                    (status, info)
                };

                let update = StatusUpdate {
                    job_id,
                    status,
                    info,
                };

                // Update cache
                {
                    let mut statuses = current_statuses.lock().unwrap();
                    statuses.insert(job_id, update.clone());
                }

                // Send update to UI
                if update_tx.send(update).is_err() {
                    // Receiver dropped, stop monitoring
                    return;
                }
            }

            // Wait for poll interval, checking for stop command periodically
            let check_interval = Duration::from_millis(100);
            let mut elapsed = Duration::ZERO;
            while elapsed < poll_interval {
                if let Ok(MonitorCommand::Stop) = command_rx.try_recv() {
                    return;
                }
                thread::sleep(check_interval);
                elapsed += check_interval;
            }
        }
    }

    /// Stop monitoring all jobs.
    pub fn stop_monitoring(&mut self) {
        if let Some(tx) = self.command_tx.take() {
            let _ = tx.send(MonitorCommand::Stop);
        }

        if let Some(handle) = self.thread_handle.take() {
            let _ = handle.join();
        }

        self.current_statuses.lock().unwrap().clear();
    }

    /// Add a job to monitoring.
    pub fn add_job_to_monitor(&self, job_id: u64) {
        if let Some(ref tx) = self.command_tx {
            let _ = tx.send(MonitorCommand::AddJob(job_id));
        }
    }

    /// Remove a job from monitoring.
    pub fn remove_job_from_monitor(&self, job_id: u64) {
        if let Some(ref tx) = self.command_tx {
            let _ = tx.send(MonitorCommand::RemoveJob(job_id));
        }
    }

    /// Get the current cached status for a job.
    #[allow(dead_code)]
    pub fn get_status(&self, job_id: u64) -> Option<StatusUpdate> {
        self.current_statuses.lock().unwrap().get(&job_id).cloned()
    }

    /// Check if a job has finished (completed or failed).
    #[allow(dead_code)]
    pub fn is_finished(&self, job_id: u64) -> bool {
        self.current_statuses
            .lock()
            .unwrap()
            .get(&job_id)
            .map(|s| matches!(s.status, JobStatus::Completed | JobStatus::Failed))
            .unwrap_or(false)
    }
}

impl Drop for StatusMonitor {
    fn drop(&mut self) {
        self.stop_monitoring();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_status_monitor_new() {
        let job_manager = Arc::new(Mutex::new(JobManager::new()));
        let monitor = StatusMonitor::new(job_manager, 3.0);
        assert!(monitor.command_tx.is_none());
        assert!(monitor.thread_handle.is_none());
    }
}
