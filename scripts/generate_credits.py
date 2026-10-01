#!/usr/bin/env python3
"""Refresh or verify Phase 10 third-party credits and release notice artifacts."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import io
import json
import re
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from urllib.request import Request, urlopen

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = ROOT / "credits" / "sources.json"
MANIFEST_PATH = ROOT / "credits" / "manifest.json"
ACKNOWLEDGMENTS_PATH = ROOT / "ACKNOWLEDGMENTS.md"
NOTICES_PATH = ROOT / "THIRD_PARTY_NOTICES.md"
LICENSE_ROOT = ROOT / "licenses"
LICENSE_INDEX_PATH = LICENSE_ROOT / "index.json"
NOTICE_SET_PATH = ROOT / "credits" / "release-notice-files.json"
LICENSE_FILE_RE = re.compile(r"^(license|copying|notice)", re.IGNORECASE)
NON_LICENSE_TEXT_RE = re.compile(r"^(authors?|contributors?)(?:[._-]|$)", re.IGNORECASE)
NOTICE_TEXT_RE = re.compile(r"^notice(?:[._-]|$)", re.IGNORECASE)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "item"


def _repo_path(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"release inventory path escapes repository: {value}")
    resolved = (ROOT / path).resolve()
    if resolved != ROOT and ROOT not in resolved.parents:
        raise ValueError(f"release inventory path escapes repository: {value}")
    return resolved


def _supported_environments() -> list[dict[str, str]]:
    base = default_environment()
    environments = []
    for system, platform, machine in (
        ("Darwin", "darwin", "arm64"),
        ("Linux", "linux", "x86_64"),
    ):
        environments.append(
            {
                **base,
                "implementation_name": "cpython",
                "platform_machine": machine,
                "platform_python_implementation": "CPython",
                "platform_system": system,
                "python_version": "3.12",
                "python_full_version": "3.12.0",
                "sys_platform": platform,
            }
        )
    return environments


def _requirements(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    environments = _supported_environments()
    for raw in path.read_text("utf-8").splitlines():
        rendered = raw.split("#", 1)[0].strip()
        if not rendered:
            continue
        requirement = Requirement(rendered)
        if requirement.marker and not any(requirement.marker.evaluate(env) for env in environments):
            continue
        versions = [item.version for item in requirement.specifier if item.operator == "=="]
        if len(versions) != 1 or len(requirement.specifier) != 1:
            raise ValueError(f"Python inventory item is not exactly pinned: {requirement.name}")
        result[canonicalize_name(requirement.name)] = versions[0]
    return result


def _python_source_url(metadata: importlib.metadata.PackageMetadata, package_name: str) -> str:
    for value in metadata.get_all("Project-URL") or []:
        _label, separator, url = value.partition(",")
        if separator and url.strip().startswith("https://"):
            return url.strip()
    homepage = str(metadata.get("Home-page") or "").strip()
    if homepage.startswith("https://"):
        return homepage
    return f"https://pypi.org/project/{quote(package_name)}/"


def _safe_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


def _write_license(source: Path, relative: str, prefix: str = "") -> str:
    destination = _repo_path(relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = prefix + _safe_text(source)
    if not text.endswith("\n"):
        text += "\n"
    destination.write_text(text, "utf-8")
    return relative


def _license_candidates(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.rglob("*") if path.is_file() and LICENSE_FILE_RE.match(path.name)
    )


def _python_license_candidates(distribution: importlib.metadata.Distribution) -> list[Path]:
    result: list[Path] = []
    for item in distribution.files or []:
        if LICENSE_FILE_RE.match(item.name):
            path = Path(distribution.locate_file(item))
            if path.is_file():
                result.append(path)
    return sorted(set(result))


def _license_text_role(path: Path | str) -> str:
    name = re.sub(r"^\d+-", "", Path(path).name)
    if NON_LICENSE_TEXT_RE.match(name):
        return "other"
    if NOTICE_TEXT_RE.match(name):
        return "notice"
    return "license"


def _license_value(metadata: importlib.metadata.PackageMetadata) -> str:
    value = metadata.get("License-Expression") or metadata.get("License") or ""
    aliases = {
        "Apache License": "Apache-2.0",
        "MIT License": "MIT",
    }
    normalized = aliases.get(value.strip(), value.strip())
    if normalized.casefold() in {"unknown", "n/a", "none"}:
        normalized = ""
    if normalized and "\n" not in normalized and "\r" not in normalized and len(normalized) <= 160:
        return normalized
    classifiers = metadata.get_all("Classifier") or []
    classifier_map = {
        "License :: OSI Approved :: Apache Software License": "Apache-2.0",
        "License :: OSI Approved :: BSD License": "BSD-3-Clause",
        "License :: OSI Approved :: MIT License": "MIT",
        "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
        "License :: OSI Approved :: Python Software Foundation License": "Python-2.0",
    }
    return next(
        (identifier for item, identifier in classifier_map.items() if item in classifiers), ""
    )


def _markdown_cell(value: object) -> str:
    return " ".join(str(value or "").split()).replace("|", "\\|")


def _node_name(lock_key: str) -> str:
    return lock_key.rsplit("node_modules/", 1)[-1]


def _node_source(name: str, version: str, spec: dict, package: dict) -> str:
    resolved = str(spec.get("resolved") or "")
    if resolved.startswith("https://"):
        return resolved
    repository = package.get("repository")
    if isinstance(repository, dict):
        repository = repository.get("url")
    value = str(repository or "").replace("git+https://", "https://")
    if value.startswith("git://github.com/"):
        value = "https://github.com/" + value.removeprefix("git://github.com/")
    if value.startswith("https://"):
        return value.removesuffix(".git")
    return f"https://www.npmjs.com/package/{quote(name, safe='@/')}/v/{quote(version)}"


def _infer_license(texts: list[str]) -> str:
    joined = "\n".join(texts).lower()
    if "permission is hereby granted, free of charge" in joined:
        return "MIT"
    if "isc license" in joined or (
        "permission to use, copy, modify" in joined and "the internet systems consortium" in joined
    ):
        return "ISC"
    if "apache license" in joined and "version 2.0" in joined:
        return "Apache-2.0"
    if "redistribution and use in source and binary forms" in joined:
        return "BSD-3-Clause" if "neither the name" in joined else "BSD-2-Clause"
    if "mozilla public license version 2.0" in joined:
        return "MPL-2.0"
    return ""


def _license_tokens(value: str) -> list[str]:
    known = (
        "MIT",
        "ISC",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "GPL-3.0-only",
        "Unlicense",
        "Python-2.0",
        "BlueOak-1.0.0",
        "0BSD",
        "Zlib",
        "CC0-1.0",
    )
    return [item for item in known if item.lower() in value.lower()]


def _node_records(sources: dict, overrides: dict[str, Path]) -> list[dict]:
    records: list[dict] = []
    for config in sources["node_locks"]:
        scope = config["scope"]
        lock_path = _repo_path(config["path"])
        node_modules = overrides.get(scope, _repo_path(config["node_modules"]))
        lock = _read_json(lock_path)
        for lock_key, spec in sorted(lock.get("packages", {}).items()):
            if not lock_key:
                continue
            package_root = node_modules / lock_key.removeprefix("node_modules/")
            package_json: dict = {}
            package_path = package_root / "package.json"
            if package_path.is_file():
                package_json = _read_json(package_path)
            name = str(package_json.get("name") or _node_name(lock_key))
            version = str(spec.get("version") or package_json.get("version") or "").strip()
            candidates = _license_candidates(package_root)
            candidate_texts = [_safe_text(path) for path in candidates]
            license_value = str(spec.get("license") or package_json.get("license") or "").strip()
            if not license_value:
                license_value = _infer_license(candidate_texts)
            entry_id = f"{scope}-{_slug(name)}-{hashlib.sha256(lock_key.encode()).hexdigest()[:10]}"
            records.append(
                {
                    "id": entry_id,
                    "name": name,
                    "category": config["category"],
                    "summary": config["summary"],
                    "version": version,
                    "license": license_value,
                    "source_url": _node_source(name, version, spec, package_json),
                    "bundled": bool(config["bundled"]),
                    "notice_required": True,
                    "source_lock": config["path"],
                    "source_path": lock_key,
                    "license_candidates": candidates,
                    "license_candidate_root": package_root,
                    "resolved": str(spec.get("resolved") or ""),
                    "integrity": str(spec.get("integrity") or ""),
                }
            )
    return records


def _download(url: str, *, sha256: str = "", integrity: str = "") -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"license source is not HTTPS: {url}")
    request = Request(url, headers={"User-Agent": "Alles-credits/1.0"})
    with urlopen(request, timeout=45) as response:
        payload = response.read(50 * 1024 * 1024 + 1)
    if len(payload) > 50 * 1024 * 1024:
        raise ValueError(f"license source is too large: {url}")
    if sha256 and hashlib.sha256(payload).hexdigest() != sha256:
        raise ValueError(f"license source hash changed: {url}")
    if integrity:
        algorithm, separator, encoded = integrity.partition("-")
        if separator != "-" or algorithm not in {"sha256", "sha384", "sha512"}:
            raise ValueError(f"unsupported package integrity: {integrity}")
        digest = hashlib.new(algorithm, payload).digest()
        if digest != base64.b64decode(encoded):
            raise ValueError(f"locked package integrity changed: {url}")
    return payload


def _write_temp_candidate(root: Path, record: dict, name: str, payload: bytes) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe license path in package archive: {name}")
    destination = root / record["id"] / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return destination


def _archive_license_candidates(record: dict, root: Path) -> list[Path]:
    resolved = record.get("resolved", "")
    if not resolved.startswith("https://registry.npmjs.org/"):
        return []
    payload = _download(resolved, integrity=record.get("integrity", ""))
    candidates: list[Path] = []
    readmes: list[tuple[str, bytes]] = []
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.size > 2 * 1024 * 1024:
                continue
            archive_path = PurePosixPath(member.name)
            if archive_path.is_absolute() or ".." in archive_path.parts:
                raise ValueError(f"unsafe license path in package archive: {member.name}")
            parts = (
                archive_path.parts[1:]
                if archive_path.parts[:1] == ("package",)
                else archive_path.parts
            )
            if not parts:
                continue
            relative = Path(*parts)
            name = relative.name
            source = archive.extractfile(member)
            if source is None:
                continue
            data = source.read()
            if LICENSE_FILE_RE.match(name):
                candidates.append(_write_temp_candidate(root, record, relative.as_posix(), data))
            elif name.lower() in {"readme", "readme.md", "readme.txt"}:
                readmes.append((relative.as_posix(), data))
    if candidates:
        return candidates
    for name, data in readmes:
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        if "permission is hereby granted" not in text.lower():
            continue
        headings = list(re.finditer(r"(?im)^#{0,3}\s*licen[cs]e\b.*$", text))
        start = headings[-1].start() if headings else text.lower().rfind("(the mit license)")
        if start >= 0:
            return [
                _write_temp_candidate(
                    root,
                    record,
                    f"embedded-{name}",
                    text[start:].encode("utf-8"),
                )
            ]
    return []


def _python_archive_license_candidates(package_name: str, version: str, root: Path) -> list[Path]:
    metadata = json.loads(
        _download(f"https://pypi.org/pypi/{quote(package_name)}/{quote(version)}/json")
    )
    artifacts = metadata.get("urls") or []
    artifact = next((item for item in artifacts if item.get("packagetype") == "sdist"), None)
    if not artifact:
        artifact = next(
            (item for item in artifacts if item.get("packagetype") == "bdist_wheel"), None
        )
    if not artifact or not str(artifact.get("url") or "").startswith("https://"):
        return []
    sha256 = str((artifact.get("digests") or {}).get("sha256") or "")
    payload = _download(str(artifact["url"]), sha256=sha256)
    files: list[tuple[str, bytes]] = []
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile() or member.size > 2 * 1024 * 1024:
                    continue
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"unsafe license path in package archive: {member.name}")
                name = relative.name
                if not LICENSE_FILE_RE.match(name):
                    continue
                source = archive.extractfile(member)
                if source is not None:
                    files.append((relative.as_posix(), source.read()))
    except tarfile.TarError:
        pass
    if not files and zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for member in archive.infolist():
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError(f"unsafe license path in package archive: {member.filename}")
                name = relative.name
                if member.is_dir() or member.file_size > 2 * 1024 * 1024:
                    continue
                if LICENSE_FILE_RE.match(name):
                    files.append((relative.as_posix(), archive.read(member)))
    return [
        _write_temp_candidate(root, {"id": f"python-{_slug(package_name)}"}, name, data)
        for name, data in sorted(files)
    ]


def _python_explicit_license_candidates(sources: dict, package_name: str, root: Path) -> list[Path]:
    candidates = []
    for item in sources.get("python_license_sources", []):
        if canonicalize_name(str(item.get("package") or "")) != package_name:
            continue
        payload = _download(str(item["url"]), sha256=str(item["sha256"]))
        candidates.append(
            _write_temp_candidate(
                root,
                {"id": f"python-{_slug(package_name)}"},
                Path(str(item["url"])).name or "LICENSE",
                payload,
            )
        )
    return candidates


def _candidate_relative_name(source: Path, roots: tuple[Path, ...]) -> str:
    for root in roots:
        try:
            return source.relative_to(root).as_posix()
        except ValueError:
            continue
    return source.name


def _explicit_license_candidates(
    sources: dict, record: dict, root: Path
) -> tuple[list[Path], bool]:
    candidates: list[Path] = []
    include_packaged = False
    for item in sources.get("node_license_sources", []):
        if item.get("package") != record["name"]:
            continue
        include_packaged = include_packaged or bool(item.get("include_packaged"))
        if item.get("path"):
            candidates.append(_repo_path(item["path"]))
        else:
            payload = _download(item["url"], sha256=item["sha256"])
            candidates.append(_write_temp_candidate(root, record, Path(item["url"]).name, payload))
    return candidates, include_packaged


def _manual_entries(sources: dict) -> list[dict]:
    entries = []
    for item in sources["manual"]:
        entry = {
            key: item[key]
            for key in (
                "id",
                "name",
                "category",
                "summary",
                "version",
                "license",
                "source_url",
                "bundled",
                "notice_required",
            )
        }
        output_prefix = f"licenses/manual/{_slug(item['id'])}"
        license_files = [
            _write_license(
                _repo_path(source),
                f"{output_prefix}/{index:02d}-{_slug(Path(source).name)}.txt",
            )
            for index, source in enumerate(item.get("license_source_files", []), start=1)
        ]
        notice_files = list(item.get("notice_source_files", []))
        if item["notice_required"] and not license_files:
            raise ValueError(f"manual inventory item lacks local license text: {item['id']}")
        for artifact_index, artifact in enumerate(item.get("artifact_files", [])):
            path = _repo_path(artifact)
            if not path.is_file():
                raise ValueError(f"manual inventory artifact is missing: {artifact}")
            version = str(item["version"])
            if (
                artifact_index == 0
                and version.startswith("sha256:")
                and _sha256(path) != version.removeprefix("sha256:")
            ):
                raise ValueError(f"manual inventory artifact hash changed: {artifact}")
        entry.update(
            {
                "license_files": license_files,
                "notice_files": notice_files,
                "artifact_files": list(item.get("artifact_files", [])),
                "inventory_source": "credits/sources.json",
            }
        )
        entries.append(entry)
    return entries


def _refresh(sources: dict, overrides: dict[str, Path]) -> dict:
    requirements = _requirements(ROOT / "requirements.lock")
    entries: list[dict] = []
    node_records = _node_records(sources, overrides)
    declared = {canonicalize_name(item["package"]): item for item in sources["python"]}

    for package_name, expected in sorted(requirements.items()):
        try:
            distribution = importlib.metadata.distribution(package_name)
        except importlib.metadata.PackageNotFoundError:
            distribution = None
        actual = distribution.version if distribution is not None else expected
        if actual != expected:
            raise ValueError(f"installed {package_name} {actual} does not match {expected}")
        metadata = distribution.metadata if distribution is not None else None
        with tempfile.TemporaryDirectory(prefix="alles-python-license-") as temporary:
            candidates = (
                _python_license_candidates(distribution) if distribution is not None else []
            )
            candidates.extend(
                _python_explicit_license_candidates(sources, package_name, Path(temporary))
            )
            if not candidates:
                candidates = _python_archive_license_candidates(
                    package_name, actual, Path(temporary)
                )
            license_value = (
                _license_value(metadata) if metadata is not None else ""
            ) or _infer_license([_safe_text(path) for path in candidates])
            if not license_value or not candidates:
                raise ValueError(f"Python inventory item lacks license evidence: {package_name}")
            prefix = f"licenses/python/{_slug(package_name)}-{actual}"
            license_files: list[str] = []
            notice_files: list[str] = []
            for index, source in enumerate(candidates, start=1):
                role = _license_text_role(source)
                if role == "other":
                    continue
                copied = _write_license(
                    source,
                    f"{prefix}/{index:02d}-{_slug(source.name)}.txt",
                )
                (notice_files if role == "notice" else license_files).append(copied)
            if not license_files:
                raise ValueError(
                    f"Python inventory item lacks authoritative license text: {package_name}"
                )
        entries.append(
            {
                "id": f"python-{_slug(package_name)}",
                "name": (metadata.get("Name") if metadata is not None else "") or package_name,
                "category": "code",
                "summary": declared.get(package_name, {}).get(
                    "summary", "transitive Python runtime dependency"
                ),
                "version": actual,
                "license": license_value,
                "source_url": declared.get(package_name, {}).get("source_url")
                or (
                    _python_source_url(metadata, package_name)
                    if metadata is not None
                    else f"https://pypi.org/project/{quote(package_name)}/"
                ),
                "bundled": True,
                "notice_required": True,
                "license_files": license_files,
                "notice_files": notice_files,
                "inventory_source": "requirements.lock",
            }
        )

    with tempfile.TemporaryDirectory(prefix="alles-credit-licenses-") as temporary:
        temporary_root = Path(temporary)
        for record in node_records:
            output_prefix = f"licenses/node/{record['id']}-{_slug(record['version'])}"
            license_files: list[str] = []
            notice_files: list[str] = []
            packaged_candidates = list(record.pop("license_candidates"))
            packaged_root = Path(record.pop("license_candidate_root"))
            explicit, include_packaged = _explicit_license_candidates(
                sources, record, temporary_root
            )
            if explicit:
                candidates = ([*packaged_candidates] if include_packaged else []) + explicit
            else:
                candidates = packaged_candidates or _archive_license_candidates(
                    record, temporary_root
                )
            record.pop("resolved", None)
            record.pop("integrity", None)
            for index, source in enumerate(candidates, start=1):
                candidate_name = _candidate_relative_name(
                    source,
                    (packaged_root, temporary_root / record["id"]),
                )
                relative = f"{output_prefix}/{index:02d}-{_slug(candidate_name)}.txt"
                copied = _write_license(source, relative)
                if source.name.lower().startswith("notice"):
                    notice_files.append(copied)
                else:
                    license_files.append(copied)
            if not record["license"]:
                raise ValueError(f"locked Node package lacks license value: {record['name']}")
            if not license_files:
                raise ValueError(
                    f"locked Node package lacks authoritative license text: {record['name']}"
                )
            entries.append(
                {
                    **record,
                    "license_files": license_files,
                    "notice_files": notice_files,
                    "inventory_source": record["source_lock"],
                }
            )

    entries.extend(_manual_entries(sources))

    entries.sort(key=lambda item: (item["category"], item["name"].casefold(), item["id"]))
    manifest = {
        "schema_version": 1,
        "state": "complete",
        "source_revision": sources["source_revision"],
        "boundaries": sources["boundaries"],
        "entries": entries,
    }
    MANIFEST_PATH.write_text(_json_text(manifest), "utf-8")
    _write_generated_docs(manifest)
    return manifest


def _refresh_manual(sources: dict) -> dict:
    existing = _read_json(MANIFEST_PATH)
    preserved = [
        entry
        for entry in existing.get("entries", [])
        if entry.get("inventory_source") != "credits/sources.json"
    ]
    entries = [*preserved, *_manual_entries(sources)]
    entries.sort(key=lambda item: (item["category"], item["name"].casefold(), item["id"]))
    manifest = {
        "schema_version": 1,
        "state": "complete",
        "source_revision": sources["source_revision"],
        "boundaries": sources["boundaries"],
        "entries": entries,
    }
    MANIFEST_PATH.write_text(_json_text(manifest), "utf-8")
    _write_generated_docs(manifest)
    return manifest


def _acknowledgments(manifest: dict) -> str:
    manual = [
        entry
        for entry in manifest["entries"]
        if entry.get("inventory_source") == "credits/sources.json"
    ]
    lines = [
        "# acknowledgments",
        "",
        "Alles is an independent project built on open-source code, public data, and clearly named",
        "inspiration. This file is generated from `credits/manifest.json`; exact package notices and",
        "local license text are in `THIRD_PARTY_NOTICES.md` and `licenses/`.",
        "",
    ]
    for entry in manual:
        lines.append(
            f"- **[{entry['name']}]({entry['source_url']})** - {entry['summary']} "
            f"(`{entry['version']}`, {entry['license']})."
        )
    lines.extend(
        [
            "",
            "The complete generated inventory contains "
            f"{len(manifest['entries'])} exact release entries, including every locked Python, "
            "CodeMirror, Actual, and Capacitor dependency.",
            "",
        ]
    )
    return "\n".join(lines)


def _notices(manifest: dict) -> str:
    lines = [
        "# third-party notices",
        "",
        "Generated from `credits/manifest.json`. Do not edit this file by hand.",
        "",
        f"source revision: `{manifest['source_revision']}`",
        "",
        "| name | version | license | source | local text |",
        "|---|---:|---|---|---|",
    ]
    for entry in manifest["entries"]:
        files = [*entry.get("license_files", []), *entry.get("notice_files", [])]
        links = "<br>".join(f"[`{Path(path).name}`]({path})" for path in files) or "not required"
        safe_name = _markdown_cell(entry["name"])
        safe_version = _markdown_cell(entry["version"])
        safe_license = _markdown_cell(entry["license"])
        lines.append(
            f"| {safe_name} | `{safe_version}` | "
            f"{safe_license} | [upstream]({entry['source_url']}) | "
            f"{links} |"
        )
    lines.extend(["", "## release boundaries", ""])
    for name, value in manifest.get("boundaries", {}).items():
        lines.append(f"- **{name.replace('_', ' ')}:** {value}")
    lines.append("")
    return "\n".join(lines)


def _prune_generated_licenses(keep: set[str]) -> None:
    for name in ("python", "node", "manual"):
        root = LICENSE_ROOT / name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                relative = path.relative_to(ROOT).as_posix()
                if relative not in keep:
                    path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass


def _write_generated_docs(manifest: dict) -> None:
    ACKNOWLEDGMENTS_PATH.write_text(_acknowledgments(manifest), "utf-8")
    NOTICES_PATH.write_text(_notices(manifest), "utf-8")
    license_paths = sorted(
        {
            path
            for entry in manifest["entries"]
            for path in [*entry.get("license_files", []), *entry.get("notice_files", [])]
            if path.startswith("licenses/")
        }
    )
    _prune_generated_licenses(set(license_paths))
    index_entries = []
    for relative in license_paths:
        path = _repo_path(relative)
        index_entries.append(
            {"path": relative, "sha256": _sha256(path), "bytes": path.stat().st_size}
        )
    LICENSE_ROOT.mkdir(parents=True, exist_ok=True)
    LICENSE_INDEX_PATH.write_text(
        _json_text(
            {
                "schema_version": 1,
                "source_revision": manifest["source_revision"],
                "files": index_entries,
            }
        ),
        "utf-8",
    )
    notice_files = [
        "ACKNOWLEDGMENTS.md",
        "THIRD_PARTY_NOTICES.md",
        "credits/manifest.json",
        "licenses/index.json",
        *license_paths,
    ]
    NOTICE_SET_PATH.write_text(
        _json_text(
            {
                "schema_version": 1,
                "source_revision": manifest["source_revision"],
                "files": notice_files,
            }
        ),
        "utf-8",
    )


def _source_tuples_from_locks(sources: dict) -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for config in sources["node_locks"]:
        lock = _read_json(_repo_path(config["path"]))
        for lock_key, spec in lock.get("packages", {}).items():
            if lock_key:
                result.add((config["path"], lock_key, str(spec.get("version") or "")))
    return result


def _check(sources: dict) -> None:
    manifest = _read_json(MANIFEST_PATH)
    if manifest.get("state") != "complete":
        raise ValueError("credits manifest is not complete")
    if manifest.get("source_revision") != sources["source_revision"]:
        raise ValueError("credits manifest source revision is stale")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("credits manifest has no entries")
    ids = [entry.get("id") for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("credits manifest has duplicate IDs")
    expected_manual = {item["id"]: item for item in sources["manual"]}
    actual_manual = {
        item["id"]: item
        for item in entries
        if item.get("inventory_source") == "credits/sources.json"
    }
    if set(expected_manual) != set(actual_manual):
        raise ValueError("manual and inspiration credits are stale")
    manual_fields = {
        "name",
        "category",
        "summary",
        "version",
        "license",
        "source_url",
        "bundled",
        "notice_required",
    }
    for entry_id, expected in expected_manual.items():
        actual = actual_manual[entry_id]
        if any(actual.get(field) != expected.get(field) for field in manual_fields):
            raise ValueError(f"manual credit is stale: {entry_id}")

    direct_requirements = _requirements(ROOT / "requirements.txt")
    locked_requirements = _requirements(ROOT / "requirements.lock")
    listed_python = {canonicalize_name(str(item["package"])) for item in sources["python"]}
    if listed_python != set(direct_requirements):
        missing = sorted(set(direct_requirements) - listed_python)
        extra = sorted(listed_python - set(direct_requirements))
        raise ValueError(
            f"Python source inventory does not match requirements; missing={missing}, extra={extra}"
        )
    if not set(direct_requirements).issubset(locked_requirements):
        raise ValueError("Python lock omits a direct requirement")
    expected_python = set(locked_requirements.items())
    actual_python = {
        (canonicalize_name(str(entry["name"])), str(entry["version"]))
        for entry in entries
        if entry.get("inventory_source") == "requirements.lock"
    }
    if actual_python != expected_python:
        raise ValueError("Python credit inventory does not match the complete runtime lock")

    expected_locks = _source_tuples_from_locks(sources)
    actual_locks = {
        (entry.get("source_lock", ""), entry.get("source_path", ""), str(entry["version"]))
        for entry in entries
        if entry.get("source_lock")
    }
    if actual_locks != expected_locks:
        raise ValueError("Node credit inventory does not match lockfiles")

    for entry in entries:
        if not str(entry.get("license") or "").strip():
            raise ValueError(f"credit entry lacks license value: {entry.get('id')}")
        texts = [*entry.get("license_files", []), *entry.get("notice_files", [])]
        if entry.get("notice_required") and not entry.get("license_files"):
            raise ValueError(f"credit entry lacks required license text: {entry.get('id')}")
        for relative in entry.get("license_files", []):
            if _license_text_role(relative) != "license":
                raise ValueError(
                    f"credit entry classifies non-license text as a license: {entry.get('id')}"
                )
        for relative in texts:
            if not _repo_path(relative).is_file():
                raise ValueError(f"credit text is missing: {relative}")

    expected_ack = _acknowledgments(manifest)
    expected_notices = _notices(manifest)
    if ACKNOWLEDGMENTS_PATH.read_text("utf-8") != expected_ack:
        raise ValueError("ACKNOWLEDGMENTS.md is stale")
    if NOTICES_PATH.read_text("utf-8") != expected_notices:
        raise ValueError("THIRD_PARTY_NOTICES.md is stale")
    index = _read_json(LICENSE_INDEX_PATH)
    expected_license_paths = sorted(
        {
            path
            for entry in entries
            for path in [*entry.get("license_files", []), *entry.get("notice_files", [])]
            if path.startswith("licenses/")
        }
    )
    indexed_paths = [item.get("path") for item in index.get("files", [])]
    if indexed_paths != expected_license_paths:
        raise ValueError("license index file inventory is incomplete or stale")
    for item in index.get("files", []):
        path = _repo_path(item["path"])
        if _sha256(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ValueError(f"license index is stale: {item['path']}")
    notice_set = _read_json(NOTICE_SET_PATH)
    expected_notice_set = [
        "ACKNOWLEDGMENTS.md",
        "THIRD_PARTY_NOTICES.md",
        "credits/manifest.json",
        "licenses/index.json",
        *expected_license_paths,
    ]
    if notice_set.get("files") != expected_notice_set:
        raise ValueError("release notice file inventory is incomplete or stale")
    for relative in notice_set.get("files", []):
        if not _repo_path(relative).is_file():
            raise ValueError(f"release notice set is missing: {relative}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--refresh-manual", action="store_true")
    parser.add_argument(
        "--node-modules",
        action="append",
        default=[],
        metavar="SCOPE=PATH",
        help="override a node_modules root while refreshing",
    )
    args = parser.parse_args()
    overrides: dict[str, Path] = {}
    for raw in args.node_modules:
        scope, separator, value = raw.partition("=")
        if not separator or not scope or not value:
            parser.error("--node-modules needs SCOPE=PATH")
        overrides[scope] = Path(value).resolve()
    sources = _read_json(SOURCES_PATH)
    if sources.get("schema_version") != 1:
        raise ValueError("unsupported credits source schema")
    if args.refresh and args.refresh_manual:
        parser.error("choose either --refresh or --refresh-manual")
    if args.refresh:
        _refresh(sources, overrides)
    elif args.refresh_manual:
        _refresh_manual(sources)
    _check(sources)


if __name__ == "__main__":
    main()
