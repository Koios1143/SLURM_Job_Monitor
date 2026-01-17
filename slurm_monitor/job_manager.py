"""Job Manager for SLURM job lifecycle management."""

import os
import re
from typing import Optional, Dict, Any, List
from .utils import run_slurm_command, parse_job_id, parse_sacct_output


class JobManager:
    """Manages SLURM job submission, tracking, and status retrieval."""
    
    def __init__(self):
        """Initialize the JobManager."""
        self.tracked_jobs: Dict[int, Dict[str, Any]] = {}
    
    def submit_job(self, sbatch_script: str, **kwargs) -> Optional[int]:
        """
        Submit a job using sbatch and return the job ID.
        
        Args:
            sbatch_script: Path to the SLURM batch script
            **kwargs: Additional arguments to pass to sbatch
            
        Returns:
            Job ID if successful, None otherwise
        """
        if not os.path.exists(sbatch_script):
            raise FileNotFoundError(f"Script not found: {sbatch_script}")
        
        cmd = ["sbatch"]
        
        # Add optional arguments
        for key, value in kwargs.items():
            if value is not None:
                if len(key) == 1:
                    cmd.extend([f"-{key}", str(value)])
                else:
                    key_formatted = key.replace("_", "-")
                    cmd.extend([f"--{key_formatted}", str(value)])
        
        cmd.append(sbatch_script)
        
        stdout, stderr, returncode = run_slurm_command(cmd)
        
        if returncode != 0:
            raise RuntimeError(f"Failed to submit job: {stderr}")
        
        job_id = parse_job_id(stdout)
        
        if job_id:
            self.tracked_jobs[job_id] = {
                'script': sbatch_script,
                'submitted': True,
            }
        
        return job_id
    
    def get_job_status(self, job_id: int) -> str:
        """
        Get the current status of a job.
        
        Args:
            job_id: The SLURM job ID
            
        Returns:
            Job status: QUEUED, RUNNING, COMPLETED, FAILED, or UNKNOWN
        """
        # First try squeue for active jobs
        stdout, stderr, returncode = run_slurm_command(
            ["squeue", "-j", str(job_id), "-h", "-o", "%T"],
            check=False
        )
        
        if returncode == 0 and stdout.strip():
            state = stdout.strip().upper()
            # Map SLURM states to our states
            state_map = {
                'PENDING': 'QUEUED',
                'RUNNING': 'RUNNING',
                'COMPLETING': 'RUNNING',
                'CONFIGURING': 'QUEUED',
            }
            return state_map.get(state, state)
        
        # If not in squeue, check sacct for completed/failed jobs
        stdout, stderr, returncode = run_slurm_command(
            ["sacct", "-j", str(job_id), "--format=State", "--noheader", "--parsable2"],
            check=False
        )
        
        if returncode == 0 and stdout.strip():
            state = stdout.strip().split('|')[0].strip().upper()
            if 'COMPLETED' in state:
                return 'COMPLETED'
            elif 'FAILED' in state or 'CANCELLED' in state or 'TIMEOUT' in state:
                return 'FAILED'
            elif 'RUNNING' in state:
                return 'RUNNING'
        
        return 'UNKNOWN'
    
    def get_job_info(self, job_id: int) -> Dict[str, Any]:
        """
        Get detailed information about a job including output paths.
        
        Args:
            job_id: The SLURM job ID
            
        Returns:
            Dictionary with job information
        """
        try:
            # Use sacct to get comprehensive job information
            stdout, stderr, returncode = run_slurm_command(
                ["sacct", "-j", str(job_id), 
                 "--format=JobID,JobName,State,Start,End,Elapsed,WorkDir,StdOut,StdErr",
                 "--parsable2"],
                check=False
            )
            
            if returncode == 0 and stdout.strip():
                info = parse_sacct_output(stdout)
                
                # Extract the main job (not array tasks)
                job_info = {}
                for key, value in info.items():
                    if not key.startswith(str(job_id) + '_'):
                        job_info[key] = value
                
                # If we got array task info, use the first one
                if not job_info and info:
                    job_info = info
                
                # Determine output paths
                work_dir = job_info.get('WorkDir', '')
                stdout_path = job_info.get('StdOut', '').strip()
                stderr_path = job_info.get('StdErr', '').strip()
                
                # Replace SLURM placeholders in paths
                # %j = job ID, %A = array job ID, %a = array task ID
                if stdout_path:
                    stdout_path = stdout_path.replace('%j', str(job_id))
                    stdout_path = stdout_path.replace('%A', str(job_id))
                    stdout_path = stdout_path.replace('%a', '0')  # Default to 0 for non-array jobs
                
                if stderr_path:
                    stderr_path = stderr_path.replace('%j', str(job_id))
                    stderr_path = stderr_path.replace('%A', str(job_id))
                    stderr_path = stderr_path.replace('%a', '0')  # Default to 0 for non-array jobs
                
                # Make paths absolute if they're relative
                if stdout_path:
                    if not os.path.isabs(stdout_path):
                        if work_dir:
                            stdout_path = os.path.join(work_dir, stdout_path)
                        else:
                            # Try current directory if no work_dir
                            stdout_path = os.path.abspath(stdout_path)
                    else:
                        stdout_path = os.path.abspath(stdout_path)
                
                if stderr_path:
                    if not os.path.isabs(stderr_path):
                        if work_dir:
                            stderr_path = os.path.join(work_dir, stderr_path)
                        else:
                            # Try current directory if no work_dir
                            stderr_path = os.path.abspath(stderr_path)
                    else:
                        stderr_path = os.path.abspath(stderr_path)
                
                return {
                    'job_id': job_id,
                    'job_name': job_info.get('JobName', ''),
                    'state': job_info.get('State', 'UNKNOWN'),
                    'start_time': job_info.get('Start', ''),
                    'end_time': job_info.get('End', ''),
                    'elapsed': job_info.get('Elapsed', ''),
                    'work_dir': work_dir,
                    'stdout_path': stdout_path,
                    'stderr_path': stderr_path,
                }
        except Exception:
            # If sacct fails, continue with fallback
            pass
        
        # Fallback: try to construct paths from common patterns
        # This is a fallback if sacct doesn't work
        # Try to find files in current directory
        cwd = os.getcwd()
        stdout_path = os.path.join(cwd, f'slurm-{job_id}.out')
        stderr_path = os.path.join(cwd, f'slurm-{job_id}.err')
        
        # Check if files exist with alternative naming
        if not os.path.exists(stdout_path):
            # Try with job array format
            alt_stdout = os.path.join(cwd, f'slurm-{job_id}_0.out')
            if os.path.exists(alt_stdout):
                stdout_path = alt_stdout
        
        if not os.path.exists(stderr_path):
            alt_stderr = os.path.join(cwd, f'slurm-{job_id}_0.err')
            if os.path.exists(alt_stderr):
                stderr_path = alt_stderr
        
        # Return paths even if files don't exist yet (they may be created later)
        return {
            'job_id': job_id,
            'job_name': '',
            'state': 'UNKNOWN',
            'start_time': '',
            'end_time': '',
            'elapsed': '',
            'work_dir': cwd,
            'stdout_path': stdout_path,
            'stderr_path': stderr_path,
        }
    
    def list_tracked_jobs(self) -> List[int]:
        """
        List all currently tracked job IDs.
        
        Returns:
            List of job IDs
        """
        return list(self.tracked_jobs.keys())
    
    def add_tracked_job(self, job_id: int, metadata: Optional[Dict[str, Any]] = None):
        """
        Add a job to the tracking list.
        
        Args:
            job_id: The SLURM job ID
            metadata: Optional metadata about the job
        """
        self.tracked_jobs[job_id] = metadata or {}
    
    def remove_tracked_job(self, job_id: int):
        """
        Remove a job from the tracking list.
        
        Args:
            job_id: The SLURM job ID
        """
        if job_id in self.tracked_jobs:
            del self.tracked_jobs[job_id]

    def get_node_resources(self, job_id: int) -> Dict[str, Any]:
        """
        Get CPU and GPU usage information for the compute node running a job.
        
        Args:
            job_id: The SLURM job ID
            
        Returns:
            Dictionary with CPU and GPU usage information (as percentages)
        """
        try:
            # First, get the node name where the job is running
            stdout, stderr, returncode = run_slurm_command(
                ["squeue", "-j", str(job_id), "-h", "-o", "%N"],
                check=False
            )
            
            node_name = None
            if returncode == 0 and stdout.strip():
                node_name = stdout.strip().split()[0] if stdout.strip() else None
            
            # If not in squeue, try sacct
            if not node_name:
                stdout, stderr, returncode = run_slurm_command(
                    ["sacct", "-j", str(job_id), "--format=NodeList", "--noheader", "--parsable2"],
                    check=False
                )
                if returncode == 0 and stdout.strip():
                    node_name = stdout.strip().split('|')[0].strip()
                    if node_name:
                        # Extract first node if it's a range like "node[001-002]"
                        node_name = node_name.split('[')[0] if '[' in node_name else node_name
            
            if not node_name or node_name == "N/A":
                return {
                    'cpu_usage': 'N/A',
                    'gpu_usage': 'N/A',
                    'node_name': 'N/A'
                }
            
            # Get CPU and GPU usage from the node using sinfo or scontrol
            cpu_info = 'N/A'
            gpu_info = 'N/A'
            
            # Try to get CPU usage from sinfo
            try:
                stdout, stderr, returncode = run_slurm_command(
                    ["sinfo", "-n", node_name, "-h", "-o", "%C"],
                    check=False
                )
                if returncode == 0 and stdout.strip():
                    # Format: "allocated/idle/other/total" or "allocated/idle/other/total"
                    cpu_info_raw = stdout.strip()
                    # Parse format like "8/0/0/8" to calculate percentage
                    parts = cpu_info_raw.split('/')
                    if len(parts) >= 4:
                        try:
                            allocated = int(parts[0])
                            total = int(parts[3])
                            if total > 0:
                                cpu_percent = int((allocated / total) * 100)
                                cpu_info = f"{cpu_percent}%"
                            else:
                                cpu_info = "0%"
                        except (ValueError, IndexError):
                            cpu_info = cpu_info_raw
                    else:
                        cpu_info = cpu_info_raw
            except Exception:
                pass
            
            # Try to get GPU usage - need to get allocated vs total GPUs
            gpu_allocated = 0
            gpu_total = 0
            
            # Method 1: Try to get GPU allocation from squeue
            try:
                stdout, stderr, returncode = run_slurm_command(
                    ["squeue", "-j", str(job_id), "-h", "-o", "%b"],
                    check=False
                )
                if returncode == 0 and stdout.strip():
                    # Parse GPU allocation (format: "gpu:1" or "gpu:2")
                    gpu_match = re.search(r'gpu:(\d+)', stdout.strip(), re.IGNORECASE)
                    if gpu_match:
                        gpu_allocated = int(gpu_match.group(1))
            except Exception:
                pass
            
            # Method 2: Try to get GPU allocation from scontrol show job
            if gpu_allocated == 0:
                try:
                    stdout, stderr, returncode = run_slurm_command(
                        ["scontrol", "show", "job", str(job_id)],
                        check=False
                    )
                    if returncode == 0 and stdout.strip():
                        # Look for GPU allocation in job info
                        # Format: "TresPerNode=gpu:1" or "Gres=gpu:1" or "ReqGRES=gpu:1"
                        for line in stdout.strip().split('\n'):
                            # Try multiple patterns
                            patterns = [
                                r'TresPerNode=.*?gpu:(\d+)',
                                r'Gres=.*?gpu:(\d+)',
                                r'ReqGRES=.*?gpu:(\d+)',
                                r'AllocGRES=.*?gpu:(\d+)',
                            ]
                            for pattern in patterns:
                                gpu_match = re.search(pattern, line, re.IGNORECASE)
                                if gpu_match:
                                    gpu_allocated = int(gpu_match.group(1))
                                    break
                            if gpu_allocated > 0:
                                break
                except Exception:
                    pass
            
            # Method 3: Try to get GPU allocation from sacct
            if gpu_allocated == 0:
                try:
                    stdout, stderr, returncode = run_slurm_command(
                        ["sacct", "-j", str(job_id), "--format=ReqGRES,AllocGRES", "--noheader", "--parsable2"],
                        check=False
                    )
                    if returncode == 0 and stdout.strip():
                        # Parse sacct output (format: "gpu:1|gpu:1" or similar)
                        for line in stdout.strip().split('\n'):
                            # Try to find GPU in either ReqGRES or AllocGRES
                            for field in line.split('|'):
                                gpu_match = re.search(r'gpu:(\d+)', field, re.IGNORECASE)
                                if gpu_match:
                                    gpu_allocated = int(gpu_match.group(1))
                                    break
                            if gpu_allocated > 0:
                                break
                except Exception:
                    pass
            
            # Get GPU total from node using scontrol show node
            try:
                stdout, stderr, returncode = run_slurm_command(
                    ["scontrol", "show", "node", node_name],
                    check=False
                )
                if returncode == 0 and stdout.strip():
                    # Parse CPUAlloc/CPUTot and Gres information
                    for line in stdout.strip().split('\n'):
                        if cpu_info == 'N/A' and 'CPUAlloc' in line and 'CPUTot' in line:
                            # Extract CPU usage
                            match = re.search(r'CPUAlloc=(\d+).*CPUTot=(\d+)', line)
                            if match:
                                alloc = int(match.group(1))
                                total = int(match.group(2))
                                if total > 0:
                                    cpu_percent = int((alloc / total) * 100)
                                    cpu_info = f"{cpu_percent}%"
                                else:
                                    cpu_info = "0%"
                        
                        # Extract total GPU count from node
                        # Try multiple patterns for Gres line
                        if 'Gres=' in line and 'gpu' in line.lower():
                            # Format examples:
                            # "Gres=gpu:8" 
                            # "Gres=gpu:4(IDX:0-3)"
                            # "Gres=gpu:2:tesla:1(IDX:0),gpu:2:tesla:1(IDX:1)"
                            # Find all GPU counts in the line
                            all_gpu_matches = re.findall(r'gpu:(\d+)', line, re.IGNORECASE)
                            if all_gpu_matches:
                                # Sum all GPU counts (handles multiple GPU types)
                                gpu_total = sum(int(x) for x in all_gpu_matches)
            except Exception:
                pass
            
            # Calculate GPU usage percentage
            if gpu_total > 0:
                if gpu_allocated > 0:
                    gpu_percent = int((gpu_allocated / gpu_total) * 100)
                    gpu_info = f"{gpu_percent}%"
                else:
                    # If we know total but job doesn't use GPU, show 0%
                    gpu_info = "0%"
            elif gpu_allocated > 0:
                # If we know allocation but not total, show allocation count
                gpu_info = f"{gpu_allocated} GPU(s)"
            
            # If we still don't have percentage format, try to convert
            if cpu_info != 'N/A' and '%' not in str(cpu_info):
                # Try to parse formats like "8/8" or "allocated/total"
                if '/' in str(cpu_info):
                    parts = str(cpu_info).split('/')
                    if len(parts) >= 2:
                        try:
                            allocated = int(parts[0])
                            total = int(parts[-1])
                            if total > 0:
                                cpu_percent = int((allocated / total) * 100)
                                cpu_info = f"{cpu_percent}%"
                        except (ValueError, IndexError):
                            pass
            
            return {
                'cpu_usage': cpu_info,
                'gpu_usage': gpu_info,
                'node_name': node_name
            }
        except Exception:
            return {
                'cpu_usage': 'N/A',
                'gpu_usage': 'N/A',
                'node_name': 'N/A'
            }
