"""
live system monitor — cpu / ram / disk / gpu snapshot for the system view.

uses psutil when present (live cpu%, per-core, real disk list, uptime); degrades
gracefully to the static hwfit detection + stdlib shutil/ctypes when it isn't, so
the page still shows ram + disk + the hardware readout, just without the live cpu%.
"""
import os
import platform
import shutil
import socket
import time


def _psutil():
    try:
        import psutil
        return psutil
    except Exception:
        return None


def _gb(n):
    return round((n or 0) / 1e9, 1)


def snapshot() -> dict:
    from services.local_models import detect_system_info
    info = detect_system_info()   # cached static hwfit readout
    ps = _psutil()

    out = {
        "live": bool(ps),   # false → no live cpu%, the rest still works
        "cpu": {"name": info.get("cpu_name") or "cpu", "cores": info.get("cpu_cores"),
                "percent": None, "per_core": [], "freq_mhz": None},
        "memory": {"total_gb": 0, "used_gb": 0, "percent": 0},
        "disks": [],
        "gpu": {"has": bool(info.get("has_gpu")), "name": info.get("gpu_name"),
                "vram_gb": info.get("gpu_vram_gb"), "count": info.get("gpu_count")},
        "host": {"os": f"{platform.system()} {platform.release()}".strip(),
                 "hostname": socket.gethostname(), "python": platform.python_version(),
                 "backend": info.get("backend")},
        "uptime_sec": None,
        "load": None,
    }

    if ps:
        # one blocking sample gives both per-core and the overall average
        per = ps.cpu_percent(interval=0.12, percpu=True)
        out["cpu"]["per_core"] = [round(x) for x in per]
        out["cpu"]["percent"] = round(sum(per) / len(per), 1) if per else None
        try:
            fr = ps.cpu_freq()
            out["cpu"]["freq_mhz"] = round(fr.current) if fr else None
        except Exception:
            pass
        vm = ps.virtual_memory()
        out["memory"] = {"total_gb": _gb(vm.total), "used_gb": _gb(vm.total - vm.available),
                         "percent": round(vm.percent, 1)}
        for p in ps.disk_partitions(all=False):
            try:
                u = ps.disk_usage(p.mountpoint)
            except Exception:
                continue
            if not u.total:
                continue
            out["disks"].append({"mount": p.mountpoint, "total_gb": _gb(u.total),
                                 "used_gb": _gb(u.used), "percent": round(u.percent, 1)})
        try:
            out["uptime_sec"] = int(time.time() - ps.boot_time())
        except Exception:
            pass
        try:
            out["load"] = [round(x, 2) for x in ps.getloadavg()]
        except Exception:
            pass
    else:
        # fallback: ram from the hwfit readout, disk from stdlib shutil
        total, avail = info.get("total_ram_gb") or 0, info.get("available_ram_gb") or 0
        used = max(0.0, total - avail)
        out["memory"] = {"total_gb": round(total, 1), "used_gb": round(used, 1),
                         "percent": round(used / total * 100, 1) if total else 0}
        try:
            here = os.path.abspath(".")
            t, u, _f = shutil.disk_usage(here)
            mount = os.path.splitdrive(here)[0] or "/"
            out["disks"].append({"mount": mount, "total_gb": _gb(t), "used_gb": _gb(u),
                                 "percent": round(u / t * 100, 1) if t else 0})
        except Exception:
            pass

    # de-dup disks by mount (psutil can list the same fs twice)
    seen, disks = set(), []
    for d in out["disks"]:
        if d["mount"] in seen:
            continue
        seen.add(d["mount"])
        disks.append(d)
    out["disks"] = disks[:6]
    return out
