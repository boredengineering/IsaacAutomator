import os
import platform
import shutil
import subprocess
import psutil

class SystemTelemetry:
    @staticmethod
    def get_system_summary():
        cpu_percent = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage('/')

        gpu_info = SystemTelemetry.get_gpu_info()

        return {
            "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "cpu_percent": cpu_percent,
            "cpu_count": psutil.cpu_count(),
            "mem_total_gb": round(mem.total / (1024 ** 3), 1),
            "mem_used_gb": round(mem.used / (1024 ** 3), 1),
            "mem_percent": mem.percent,
            "disk_percent": disk.percent,
            "disk_total_gb": round(disk.total / (1024 ** 3), 1),
            "disk_free_gb": round(disk.free / (1024 ** 3), 1),
            "gpus": gpu_info
        }

    @staticmethod
    def get_gpu_info():
        nvidia_smi = shutil.which("nvidia-smi")
        if not nvidia_smi:
            return []

        try:
            cmd = [
                nvidia_smi,
                "--query-gpu=index,name,driver_version,memory.total,memory.used,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if res.returncode != 0 or not res.stdout.strip():
                return []

            gpus = []
            for line in res.stdout.strip().split("\n"):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 7:
                    gpus.append({
                        "index": parts[0],
                        "name": parts[1],
                        "driver": parts[2],
                        "mem_total_mb": int(parts[3]),
                        "mem_used_mb": int(parts[4]),
                        "temp_c": int(parts[5]),
                        "util_percent": int(parts[6]),
                    })
            return gpus
        except Exception:
            return []
