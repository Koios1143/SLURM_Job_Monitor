//! Utility functions for SLURM command execution and output parsing.

use anyhow::{Context, Result};
use regex::Regex;
use std::collections::HashMap;
use std::process::Command;

/// Result of running a SLURM command
#[derive(Debug)]
pub struct CommandResult {
    pub stdout: String,
    pub stderr: String,
    pub return_code: i32,
}

/// Execute a SLURM command and return stdout, stderr, and return code.
///
/// # Arguments
/// * `cmd` - Command and arguments as a slice
/// * `check` - If true, return error on non-zero return code
/// * `timeout_secs` - Command timeout in seconds (default: 30)
pub fn run_slurm_command(cmd: &[&str], check: bool) -> Result<CommandResult> {
    run_slurm_command_with_timeout(cmd, check, 30)
}

/// Execute a SLURM command with custom timeout.
pub fn run_slurm_command_with_timeout(
    cmd: &[&str],
    check: bool,
    _timeout_secs: u64,
) -> Result<CommandResult> {
    if cmd.is_empty() {
        anyhow::bail!("Empty command");
    }

    let output = Command::new(cmd[0])
        .args(&cmd[1..])
        .output()
        .with_context(|| format!("Failed to execute command: {}", cmd[0]))?;

    let result = CommandResult {
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
        return_code: output.status.code().unwrap_or(-1),
    };

    if check && result.return_code != 0 {
        anyhow::bail!(
            "Command {:?} failed with code {}: {}",
            cmd,
            result.return_code,
            result.stderr
        );
    }

    Ok(result)
}

/// Parse job ID from sbatch output.
///
/// Typical sbatch output: "Submitted batch job 12345"
pub fn parse_job_id(sbatch_output: &str) -> Option<u64> {
    let re = Regex::new(r"Submitted batch job (\d+)").ok()?;
    re.captures(sbatch_output)
        .and_then(|caps| caps.get(1))
        .and_then(|m| m.as_str().parse().ok())
}

/// Parse squeue output for a single job.
#[allow(dead_code)]
pub fn parse_squeue_output(output: &str) -> HashMap<String, String> {
    let mut result = HashMap::new();
    let lines: Vec<&str> = output.trim().lines().collect();

    if lines.len() < 2 {
        return result;
    }

    // Skip header line
    let data_line = lines[1].trim();
    let parts: Vec<&str> = data_line.split_whitespace().collect();

    if parts.len() >= 4 {
        result.insert("job_id".to_string(), parts[0].to_string());
        result.insert("state".to_string(), parts.get(1).unwrap_or(&"UNKNOWN").to_string());
        result.insert("time".to_string(), parts.get(2).unwrap_or(&"").to_string());
        result.insert("nodes".to_string(), parts.get(3).unwrap_or(&"").to_string());
    }

    result
}

/// Parse sacct output for job information.
/// Handles multiple rows (main job + batch step) by merging data,
/// preferring non-empty values from batch steps for StdOut/StdErr.
pub fn parse_sacct_output(output: &str) -> HashMap<String, String> {
    let mut result = HashMap::new();
    let lines: Vec<&str> = output
        .trim()
        .lines()
        .filter(|l| !l.trim().is_empty())
        .collect();

    if lines.len() < 2 {
        return result;
    }

    // Parse header
    let header: Vec<&str> = lines[0].split('|').collect();
    
    // First pass: populate from main job line (lines[1])
    let data: Vec<&str> = lines[1].split('|').collect();
    for (i, field) in header.iter().enumerate() {
        if i < data.len() {
            result.insert(field.trim().to_string(), data[i].trim().to_string());
        }
    }

    // Second pass: look for StdOut/StdErr in subsequent lines (batch steps like .0, .batch)
    // These fields are often only populated on the batch step, not the main job
    for line in lines.iter().skip(2) {
        let data: Vec<&str> = line.split('|').collect();
        for (i, field) in header.iter().enumerate() {
            let field_name = field.trim();
            if (field_name == "StdOut" || field_name == "StdErr") && i < data.len() {
                let value = data[i].trim();
                if !value.is_empty() {
                    // Found a non-empty StdOut/StdErr, use it
                    result.insert(field_name.to_string(), value.to_string());
                }
            }
        }
    }

    result
}

/// Parse sacct output for multiple jobs.
#[allow(dead_code)]
pub fn parse_sacct_multiple_output(output: &str) -> Vec<HashMap<String, String>> {
    let lines: Vec<&str> = output
        .trim()
        .lines()
        .filter(|l| !l.trim().is_empty())
        .collect();

    if lines.len() < 2 {
        return Vec::new();
    }

    // Parse header
    let header: Vec<&str> = lines[0].split('|').collect();

    // Parse all data lines
    lines[1..]
        .iter()
        .map(|line| {
            let data: Vec<&str> = line.split('|').collect();
            let mut result = HashMap::new();
            for (i, field) in header.iter().enumerate() {
                if i < data.len() {
                    result.insert(field.trim().to_string(), data[i].trim().to_string());
                }
            }
            result
        })
        .filter(|m| !m.is_empty())
        .collect()
}

/// Get all job IDs from sacct (recent jobs visible to the user).
///
/// Returns a vector of job IDs sorted in descending order.
pub fn get_all_job_ids_from_sacct() -> Vec<u64> {
    let result = run_slurm_command(
        &["sacct", "--format=JobID", "--noheader", "--parsable2"],
        false,
    );

    match result {
        Ok(cmd_result) if cmd_result.return_code == 0 && !cmd_result.stdout.trim().is_empty() => {
            let mut job_ids: Vec<u64> = cmd_result
                .stdout
                .trim()
                .lines()
                .filter_map(|line| {
                    let line = line.trim();
                    if line.is_empty() {
                        return None;
                    }
                    // Extract job ID (may be in format like "12345" or "12345.batch" or "12345_0")
                    let job_id_str = line
                        .split('|')
                        .next()?
                        .split('.')
                        .next()?
                        .split('_')
                        .next()?;
                    job_id_str.parse().ok()
                })
                .collect();

            // Remove duplicates and sort in descending order
            job_ids.sort_unstable();
            job_ids.dedup();
            job_ids.reverse();
            job_ids
        }
        _ => Vec::new(),
    }
}

/// Job status enum
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JobStatus {
    Queued,
    Running,
    Completed,
    Failed,
    Unknown,
}

impl JobStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            JobStatus::Queued => "QUEUED",
            JobStatus::Running => "RUNNING",
            JobStatus::Completed => "COMPLETED",
            JobStatus::Failed => "FAILED",
            JobStatus::Unknown => "UNKNOWN",
        }
    }

    pub fn from_slurm_state(state: &str) -> Self {
        let state_upper = state.to_uppercase();
        match state_upper.as_str() {
            "PENDING" | "CONFIGURING" => JobStatus::Queued,
            "RUNNING" | "COMPLETING" => JobStatus::Running,
            "COMPLETED" => JobStatus::Completed,
            "FAILED" | "CANCELLED" | "TIMEOUT" | "NODE_FAIL" | "PREEMPTED" | "OUT_OF_MEMORY" => {
                JobStatus::Failed
            }
            _ => {
                if state_upper.contains("COMPLETED") {
                    JobStatus::Completed
                } else if state_upper.contains("FAILED")
                    || state_upper.contains("CANCELLED")
                    || state_upper.contains("TIMEOUT")
                {
                    JobStatus::Failed
                } else if state_upper.contains("RUNNING") {
                    JobStatus::Running
                } else {
                    JobStatus::Unknown
                }
            }
        }
    }
}

impl std::fmt::Display for JobStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_job_id() {
        assert_eq!(
            parse_job_id("Submitted batch job 12345"),
            Some(12345)
        );
        assert_eq!(
            parse_job_id("Submitted batch job 999999999"),
            Some(999999999)
        );
        assert_eq!(parse_job_id("Invalid output"), None);
    }

    #[test]
    fn test_parse_sacct_output() {
        let output = "JobID|JobName|State\n12345|test_job|RUNNING\n";
        let result = parse_sacct_output(output);
        assert_eq!(result.get("JobID"), Some(&"12345".to_string()));
        assert_eq!(result.get("JobName"), Some(&"test_job".to_string()));
        assert_eq!(result.get("State"), Some(&"RUNNING".to_string()));
    }

    #[test]
    fn test_job_status_from_slurm_state() {
        assert_eq!(JobStatus::from_slurm_state("PENDING"), JobStatus::Queued);
        assert_eq!(JobStatus::from_slurm_state("RUNNING"), JobStatus::Running);
        assert_eq!(JobStatus::from_slurm_state("COMPLETED"), JobStatus::Completed);
        assert_eq!(JobStatus::from_slurm_state("FAILED"), JobStatus::Failed);
        assert_eq!(JobStatus::from_slurm_state("CANCELLED"), JobStatus::Failed);
    }
}
