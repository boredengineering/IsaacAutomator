#!/usr/bin/env python3
"""
Hardware & GPU Architecture Probe for Physical AI Workstations
Detects NVIDIA GPU microarchitecture, compute capability (sm_120, sm_89, sm_90),
driver version, CUDA runtime, and C++ fatbin compatibility.
"""
import sys
import subprocess
import json

def probe_hardware():
    report = {
        "gpu_detected": False,
        "gpu_name": "Unknown",
        "driver_version": "Unknown",
        "compute_capability": "Unknown",
        "blackwell_sm120": False,
        "torch_cuda_available": False,
        "torch_arch_list": []
    }
    
    try:
        smi_out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader"],
            encoding="utf-8"
        ).strip()
        if smi_out:
            parts = [p.strip() for p in smi_out.splitlines()[0].split(",")]
            report["gpu_detected"] = True
            report["gpu_name"] = parts[0]
            report["driver_version"] = parts[1]
            report["compute_capability"] = parts[2]
            if parts[2] in ["12.0", "10.0"]:
                report["blackwell_sm120"] = True
    except Exception as e:
        report["gpu_error"] = str(e)

    try:
        import torch
        report["torch_version"] = torch.__version__
        report["torch_cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            report["torch_arch_list"] = torch.cuda.get_arch_list()
    except ImportError:
        report["torch_version"] = "Not installed"

    return report

if __name__ == "__main__":
    data = probe_hardware()
    print(json.dumps(data, indent=2))
