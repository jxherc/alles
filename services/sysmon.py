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


def _os_name() -> str:
    """platform.release() lies on windows 11 — it still says '10' because win11
    reports version 10.0.x. the build number is the only tell (>=22000 = win11)."""
    sysname = platform.system()
    if sysname == "Windows":
        try:
            build = int(platform.version().split(".")[2])  # '10.0.26100' -> 26100
        except (IndexError, ValueError):
            build = 0
        return f"Windows {'11' if build >= 22000 else platform.release()}"
    if sysname == "Darwin":
        ver = platform.mac_ver()[0]
        return f"macOS {ver}".strip() if ver else "macOS"
    return f"{sysname} {platform.release()}".strip()


def _arch() -> str:
    # 'AMD64' is just the x86-64 ISA name (amd designed it, intel licensed it) —
    # windows reports it for every 64-bit box, intel or amd. show the neutral name.
    m = platform.machine()
    return {
        "AMD64": "x86_64",
        "x86_64": "x86_64",
        "x86": "x86",
        "i386": "x86",
        "i686": "x86",
        "ARM64": "arm64",
        "aarch64": "arm64",
    }.get(m, m or "?")


# module-level state for rate calcs (the server process persists across polls)
_net_last = None  # (monotonic, bytes_sent, bytes_recv)
_dio_last = None  # (monotonic, read_bytes, write_bytes)


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
    return {
        "up_bps": up,
        "down_bps": down,
        "sent_total": io.bytes_sent,
        "recv_total": io.bytes_recv,
    }


def _primary_ip():
    """the source ip of the default route — picks the REAL outbound nic, not a
    virtual hyper-v/docker/vmware adapter that might enumerate first. no packets sent."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


_VIRT = ("veth", "vethernet", "loopback", "vmware", "virtualbox", "docker", "wsl", "hyper-v")


def _net_iface(ps) -> dict:
    """the primary interface + its ipv4 — for the net panel header."""
    try:
        stats = ps.net_if_stats()
        addrs = ps.net_if_addrs()
    except Exception:
        return {}
    spd_of = lambda n: getattr(stats.get(n), "speed", 0) or 0
    # 1. match the default-route ip to whichever interface owns it (the real one)
    primary = _primary_ip()
    if primary:
        for name, al in addrs.items():
            if any(
                getattr(a, "family", None) == socket.AF_INET and a.address == primary for a in al
            ):
                return {"iface": name[:18], "ip": primary, "link_mbps": spd_of(name)}
    # 2. fallback: first up, non-loopback, non-virtual interface with an ipv4
    for name, st in stats.items():
        low = name.lower()
        if not st.isup or low.startswith("lo") or any(v in low for v in _VIRT):
            continue
        for a in addrs.get(name, []):
            if getattr(a, "family", None) == socket.AF_INET and not a.address.startswith("127."):
                return {"iface": name[:18], "ip": a.address, "link_mbps": spd_of(name)}
    return {}


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


_user_cache = {}  # pid -> username (stable per process; lookups are slow on windows)


def _processes(ps, limit=24) -> tuple[list, int]:
    """top processes by cpu, btop-style columns (threads/user/mem/cpu). process_iter
    caches Process objects, so cpu_percent() measures the delta since the previous
    poll (first poll reads ~0 — same as btop warming up)."""
    # pass 1: cheap cpu read for every process (cpu_percent on the cached object)
    cand = []
    for p in ps.process_iter(["pid", "name"]):
        pid, name = p.info.get("pid"), (p.info.get("name") or "?")
        if pid == 0 or name == "System Idle Process":  # win idle process = noise
            continue
        try:
            cand.append((p.cpu_percent(None), pid, name, p))
        except Exception:
            continue
    total = len(cand)
    cand.sort(key=lambda x: x[0], reverse=True)

    # pass 2: the expensive per-process detail only for the top N we'll actually show
    procs = []
    for cpu, pid, name, p in cand[:limit]:
        try:
            with p.oneshot():
                mem = p.memory_percent()
                rss = p.memory_info().rss
                try:
                    threads = p.num_threads()
                except Exception:
                    threads = 0
        except Exception:
            mem, rss, threads = 0.0, 0, 0
        user = _user_cache.get(pid)
        if user is None:
            try:
                user = (p.username() or "").split("\\")[-1][:12]
            except Exception:
                user = ""
            _user_cache[pid] = user
        procs.append(
            {
                "pid": pid,
                "name": name[:28],
                "cpu": round(cpu, 1),
                "mem": round(mem, 1),
                "rss": rss,
                "threads": threads,
                "user": user,
            }
        )
    if len(_user_cache) > 4000:
        _user_cache.clear()
    return procs, total


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

    info = detect_system_info()  # cached static hwfit readout
    ps = _psutil()

    out = {
        "live": bool(ps),  # false → no live cpu%, the rest still works
        "cpu": {
            "name": info.get("cpu_name") or "cpu",
            "cores": info.get("cpu_cores"),
            "percent": None,
            "per_core": [],
            "freq_mhz": None,
        },
        "memory": {"total_gb": 0, "used_gb": 0, "percent": 0},
        "disks": [],
        "gpu": {
            "has": bool(info.get("has_gpu")),
            "name": info.get("gpu_name"),
            "vram_gb": info.get("gpu_vram_gb"),
            "count": info.get("gpu_count"),
        },
        "host": {
            "os": _os_name(),
            "platform": platform.system().lower(),
            "hostname": socket.gethostname(),
            "python": platform.python_version(),
            "user": _user(),
            "arch": _arch(),
            "backend": info.get("backend"),
        },
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
        out["memory"] = {
            "total_gb": _gb(vm.total),
            "used_gb": _gb(vm.total - vm.available),
            "available_gb": _gb(vm.available),
            "percent": round(vm.percent, 1),
            "free_gb": _gb(getattr(vm, "free", 0) or 0),
            "cached_gb": _gb(getattr(vm, "cached", 0) or getattr(vm, "buffers", 0) or 0),
        }
        try:
            sw = ps.swap_memory()
            out["swap"] = {
                "total_gb": _gb(sw.total),
                "used_gb": _gb(sw.used),
                "percent": round(sw.percent, 1),
            }
        except Exception:
            pass
        out["net"] = {**_net_rates(ps), **_net_iface(ps)}
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
            out["disks"].append(
                {
                    "mount": p.mountpoint,
                    "total_gb": _gb(u.total),
                    "used_gb": _gb(u.used),
                    "free_gb": _gb(u.free),
                    "percent": round(u.percent, 1),
                    "fstype": (p.fstype or "")[:8],
                }
            )
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
        out["memory"] = {
            "total_gb": round(total, 1),
            "used_gb": round(used, 1),
            "percent": round(used / total * 100, 1) if total else 0,
        }
        try:
            here = os.path.abspath(".")
            t, u, _f = shutil.disk_usage(here)
            mount = os.path.splitdrive(here)[0] or "/"
            out["disks"].append(
                {
                    "mount": mount,
                    "total_gb": _gb(t),
                    "used_gb": _gb(u),
                    "percent": round(u / t * 100, 1) if t else 0,
                }
            )
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
