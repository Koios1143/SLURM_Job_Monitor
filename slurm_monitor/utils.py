"""Utility functions for SLURM monitor."""

import subprocess
import re
from typing import Optional, Dict, Any


def run_slurm_command(cmd: list, check: bool = True) -> tuple[str, str, int]:
    """
    Execute a SLURM command and return stdout, stderr, and return code.
    
    Args:
        cmd: Command and arguments as a list
        check: If True, raise exception on non-zero return code
        
    Returns:
        Tuple of (stdout, stderr, return_code)
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
            timeout=30
        )
        return result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command {cmd} timed out")
    except subprocess.CalledProcessError as e:
        if check:
            raise RuntimeError(f"Command {cmd} failed: {e.stderr}")
        return e.stdout, e.stderr, e.returncode
    except FileNotFoundError:
        raise RuntimeError(f"SLURM command not found: {cmd[0]}")


def parse_job_id(sbatch_output: str) -> Optional[int]:
    """
    Parse job ID from sbatch output.
    
    Typical sbatch output: "Submitted batch job 12345"
    
    Args:
        sbatch_output: Output from sbatch command
        
    Returns:
        Job ID as integer, or None if not found
    """
    match = re.search(r'Submitted batch job (\d+)', sbatch_output)
    if match:
        return int(match.group(1))
    return None


def parse_squeue_output(output: str) -> Dict[str, Any]:
    """
    Parse squeue output for a single job.
    
    Args:
        output: Output from squeue command
        
    Returns:
        Dictionary with job information
    """
    lines = output.strip().split('\n')
    if len(lines) < 2:
        return {}
    
    # Skip header line
    data_line = lines[1].strip()
    parts = data_line.split()
    
    if len(parts) < 4:
        return {}
    
    return {
        'job_id': parts[0],
        'state': parts[1] if len(parts) > 1 else 'UNKNOWN',
        'time': parts[2] if len(parts) > 2 else '',
        'nodes': parts[3] if len(parts) > 3 else '',
    }


def parse_sacct_output(output: str) -> Dict[str, Any]:
    """
    Parse sacct output for job information.
    
    Args:
        output: Output from sacct command
        
    Returns:
        Dictionary with job information including paths
    """
    lines = [line.strip() for line in output.strip().split('\n') if line.strip()]
    if len(lines) < 2:
        return {}
    
    # Parse header and data
    header = lines[0].split('|')
    data = lines[1].split('|')
    
    result = {}
    for i, field in enumerate(header):
        if i < len(data):
            result[field.strip()] = data[i].strip()
    
    return result
