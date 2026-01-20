from setuptools import setup, find_packages

setup(
    name="slurm-monitor",
    version="0.1.0",
    description="Real-time SLURM job monitoring tool with live stdout/stderr viewing",
    author="Your Name",
    packages=find_packages(),
    install_requires=[
        "rich>=13.0.0",
        "watchdog>=3.0.0",
        "click>=8.0.0",
        "keyboard>=0.13.5",
    ],
    entry_points={
        "console_scripts": [
            "slurm-monitor-py=slurm_monitor.cli:main",
        ],
    },
    python_requires=">=3.8",
)
