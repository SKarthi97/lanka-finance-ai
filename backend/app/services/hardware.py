import shutil
import subprocess

import psutil

GB = 1024**3


def recommend_model(free_ram_gb: float, has_gpu: bool) -> str:
    """Model size guidance from docs/00-architecture.md section 6.

    The doc leaves 20-24 GB unspecified; it is treated as the 4B tier.
    """
    if has_gpu or free_ram_gb >= 24:
        return "8B"
    if free_ram_gb >= 10:
        return "4B"
    return "1.7-3B"


def _detect_gpu() -> dict:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {"present": False, "name": None}
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        return {"present": bool(out), "name": out.splitlines()[0] if out else None}
    except (subprocess.SubprocessError, OSError):
        return {"present": False, "name": None}


def hardware_report(disk_path: str = "/") -> dict:
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(disk_path)
    gpu = _detect_gpu()
    free_gb = memory.available / GB

    return {
        "cpu_threads": psutil.cpu_count(logical=True),
        "cpu_cores": psutil.cpu_count(logical=False),
        "ram_total_gb": round(memory.total / GB, 1),
        "ram_available_gb": round(free_gb, 1),
        "disk_total_gb": round(disk.total / GB, 1),
        "disk_free_gb": round(disk.free / GB, 1),
        "gpu": gpu,
        "recommended_model_size": recommend_model(free_gb, gpu["present"]),
    }
