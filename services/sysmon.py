"""
live system monitor — cpu / ram / disk / gpu snapshot for the system view.

uses psutil when present (live cpu%, per-core, real disk list, uptime); degrades
gracefully to the static hwfit detection + stdlib shutil/ctypes when it isn't, so
the page still shows ram + disk + the hardware readout, just without the live cpu%.
"""
import getpass
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


def _user():
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("USERNAME") or "user"


# module-level state for rate calcs (the server process persists across polls)
_net_last = None    # (monotonic, bytes_sent, bytes_recv)
_dio_last = None    # (monotonic, read_bytes, write_bytes)


def _net_rates(ps) -> dict:
    global _net_last
    try:
        io = ps.net_io_counters()
    except Exception:
        return {}
    now = time.monotonic()
    up = down = 0.0
    if _net_last:
        dt = now - _net_last[0]
        if dt > 0:
            up = max(0.0, (io.bytes_sent - _net_last[1]) / dt)
            down = max(0.0, (io.bytes_recv - _net_last[2]) / dt)
    _net_last = (now, io.bytes_sent, io.bytes_recv)
    return {"up_bps": up, "down_bps": down,
            "sent_total": io.bytes_sent, "recv_total": io.bytes_recv}


def _disk_io_rates(ps) -> dict:
    global _dio_last
    try:
        io = ps.disk_io_counters()
    except Exception:
        return {}
    if not io:
        return {}
    now = time.monotonic()
    rd = wr = 0.0
    if _dio_last:
        dt = now - _dio_last[0]
        if dt > 0:
            rd = max(0.0, (io.read_bytes - _dio_last[1]) / dt)
            wr = max(0.0, (io.write_bytes - _dio_last[2]) / dt)
    _dio_last = (now, io.read_bytes, io.write_bytes)
    return {"read_bps": rd, "write_bps": wr}


def _processes(ps, limit=16) -> tuple[list, int]:
    """top processes by cpu. process_iter caches Process objects, so cpu_percent()
    measures the delta since the previous poll (first poll reads ~0 for everything,
    real numbers from the second on — same as btop warming up)."""
    procs = []
    for p in ps.process_iter(["pid", "name"]):
        pid, name = p.info.get("pid"), (p.info.get("name") or "?")
        # the windows idle process aggregates every idle core (~ncores*100%) — noise
        if pid == 0 or name == "System Idle Process":
            continue
        try:
            cpu = p.cpu_percent(None)
            mem = p.memory_percent()
        except Exception:
            continue
        procs.append({"pid": pid, "name": name[:26], "cpu": round(cpu, 1), "mem": round(mem, 1)})
    total = len(procs)
    procs.sort(key=lambda x: (x["cpu"], x["mem"]), reverse=True)
    return procs[:limit], total


def _temps(ps):
    try:
        t = ps.sensors_temperatures()
    except Exception:
        return None
    if not t:
        return None
    # pick a plausible cpu sensor
    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower"):
        if key in t and t[key]:
            cur = t[key][0].current
            if cur:
                return round(cur)
    for arr in t.values():
        if arr and arr[0].current:
            return round(arr[0].current)
    return None


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
                 "platform": platform.system().lower(),
                 "hostname": socket.gethostname(), "python": platform.python_version(),
                 "user": _user(), "arch": platform.machine(),
                 "backend": info.get("backend")},
        "uptime_sec": None,
        "load": None,
        "swap": None,
        "net": {},
        "disk_io": {},
        "procs": [],
        "proc_count": 0,
        "temp_c": None,
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
                         "available_gb": _gb(vm.available), "percent": round(vm.percent, 1),
                         "cached_gb": _gb(getattr(vm, "cached", 0) or getattr(vm, "buffers", 0) or 0)}
        try:
            sw = ps.swap_memory()
            out["swap"] = {"total_gb": _gb(sw.total), "used_gb": _gb(sw.used),
                           "percent": round(sw.percent, 1)}
        except Exception:
            pass
        out["net"] = _net_rates(ps)
        out["disk_io"] = _disk_io_rates(ps)
        out["temp_c"] = _temps(ps)
        try:
            out["procs"], out["proc_count"] = _processes(ps)
        except Exception:
            pass
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
