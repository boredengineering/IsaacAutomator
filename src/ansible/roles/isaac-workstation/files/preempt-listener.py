#!/usr/bin/env python3

# region copyright
# Copyright 2023-2026 NVIDIA Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# endregion

"""
GCP Preemption Listener Daemon
Polls the GCP instance metadata server for preemption notice (30s warning),
gracefully stops training / simulation workloads, and flushes checkpoints to GCS.
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error

METADATA_PREEMPTED_URL = "http://metadata.google.internal/computeMetadata/v1/instance/preempted"
METADATA_HEADERS = {"Metadata-Flavor": "Google"}
LOG_FILE = "/var/log/isaac-preempt.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)


def check_preempted() -> bool:
    """Check if GCP metadata server reports preemption."""
    try:
        req = urllib.request.Request(METADATA_PREEMPTED_URL, headers=METADATA_HEADERS)
        with urllib.request.urlopen(req, timeout=3) as resp:
            content = resp.read().decode("utf-8").strip()
            return content.upper() == "TRUE"
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        # On non-GCP or transient network glitch, ignore
        return False


def signal_training_processes():
    """Find Isaac Sim / Python workloads and send SIGINT to trigger checkpoint serialization."""
    logging.info("Sending SIGINT to active Isaac Sim / Python workloads...")
    try:
        # Find pids of python processes matching isaac or omni
        ps = subprocess.run(
            ["pgrep", "-f", "python.*(isaac|omni|train)"],
            capture_output=True,
            text=True,
        )
        if ps.returncode == 0 and ps.stdout.strip():
            pids = ps.stdout.strip().split()
            for pid in pids:
                try:
                    os.kill(int(pid), signal.SIGINT)
                    logging.info(f"Sent SIGINT to process PID {pid}")
                except ProcessLookupError:
                    pass
        else:
            logging.info("No active training processes found matching filter.")
    except Exception as e:
        logging.warning(f"Error signaling workloads: {e}")


def sync_to_gcs(results_dir: str, gcs_bucket: str, deployment_name: str):
    """Perform emergency synchronization of results/checkpoints to GCS."""
    if not gcs_bucket or not results_dir or not os.path.exists(results_dir):
        logging.info("GCS bucket or results directory not configured; skipping sync.")
        return

    gcs_target = f"gs://{gcs_bucket.rstrip('/')}/{deployment_name}/results/"
    logging.info(f"Starting emergency sync from {results_dir} to {gcs_target}...")
    try:
        # Try gcloud storage rsync first, fallback to gsutil rsync
        cmd = ["gcloud", "storage", "rsync", results_dir, gcs_target, "--recursive"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if res.returncode == 0:
            logging.info("Emergency sync to GCS completed successfully.")
        else:
            logging.error(f"gcloud storage rsync failed: {res.stderr}. Attempting gsutil fallback...")
            cmd_fallback = ["gsutil", "-m", "rsync", "-r", results_dir, gcs_target]
            res_fallback = subprocess.run(cmd_fallback, capture_output=True, text=True, timeout=15)
            if res_fallback.returncode == 0:
                logging.info("Fallback gsutil sync completed successfully.")
            else:
                logging.error(f"Fallback gsutil sync failed: {res_fallback.stderr}")
    except Exception as e:
        logging.error(f"Failed to execute emergency GCS sync: {e}")


def main():
    parser = argparse.ArgumentParser(description="GCP Spot/Flex Preemption Watchdog")
    parser.add_argument("--results-dir", default="/home/ubuntu/results", help="Path to local results/checkpoints")
    parser.add_argument("--gcs-bucket", default=os.getenv("GCS_BACKUP_BUCKET", ""), help="Target GCS bucket name")
    parser.add_argument("--deployment-name", default=os.getenv("DEPLOYMENT_NAME", "default"), help="Deployment name")
    parser.add_argument("--poll-interval", type=int, default=5, help="Polling interval in seconds")
    args = parser.parse_args()

    logging.info(f"Starting GCP Preemption Listener (poll interval: {args.poll_interval}s, bucket: {args.gcs_bucket or 'None'})")

    running = True

    def handle_sigterm(signum, frame):
        nonlocal running
        logging.info("Received termination signal, shutting down daemon cleanly.")
        running = False

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    while running:
        if check_preempted():
            logging.warning("!!! GCP PREEMPTION DETECTED (30s WARNING TRIGGERED) !!!")
            
            # Step 1: Signal simulation/training to flush weights
            signal_training_processes()
            
            # Step 2: Give processes brief moment to flush
            time.sleep(4)
            
            # Step 3: Emergency sync to GCS
            sync_to_gcs(args.results_dir, args.gcs_bucket, args.deployment_name)
            
            # Step 4: Write completion marker
            try:
                with open("/tmp/isaac-preempted", "w") as f:
                    f.write(f"Preempted at {time.time()}\n")
            except Exception:
                pass
            
            logging.info("Preemption handler finished. Standing by for shutdown.")
            break
            
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
