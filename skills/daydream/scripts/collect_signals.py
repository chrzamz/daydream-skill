#!/usr/bin/env python3
"""Optionally collect local signals; reads only explicitly selected paths.

Python 3.9+, standard library only. No network, source writes, or saved cache.
Credential filtering is conservative and incomplete: review before sharing output.
Markdown dates describe file edits, never when an idea was created.
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys


SECRET_TITLE = re.compile(
    r"(?i)(?:^\s*(?:keys?|tokens?|secrets?|auth)\s*$|password|passwd|credentials?|api[ _-]?(?:key|token)|"
    r"app[ _-]?secret|client[ _-]?secret|access[ _-]?(?:key|token)|"
    r"private[ _-]?key|secret[ _-]?key|密码|口令|密钥|秘钥|私钥|凭据|凭证|访问令牌)"
)
SECRET_KEY = (
    r"(?:password|passwd|pwd|api[ _-]?key|app[ _-]?secret|client[ _-]?secret|"
    r"access[ _-]?(?:token|key(?:[ _-]?secret)?)|refresh[ _-]?token|"
    r"secret[ _-]?(?:key|token)|token|密码|口令|(?:API|应用|访问)?密钥|"
    r"秘钥|凭据|凭证|访问令牌)"
)
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    re.compile(r"(?i)(?<![\w-])(?:sk-(?:proj-|ant-|svcacct-)?[a-z0-9_-]{12,}|"
               r"sk_(?:live|test)_[a-z0-9]{16,}|re_[a-z0-9_]{16,}|"
               r"gh[pousr]_[a-z0-9]{12,}|github_pat_[a-z0-9_]{12,}|"
               r"glpat-[a-z0-9_-]{12,}|xox[baprs]-[a-z0-9-]{10,}|"
               r"hf_[a-z0-9]{16,}|AIza[a-z0-9_-]{20,}|"
               r"(?:AKIA|ASIA)[A-Z0-9]{16})(?![\w-])"),
    re.compile(r"(?<!\w)eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
               r"[A-Za-z0-9_-]{8,}(?!\w)"),
    re.compile(r"(?i)(?<![A-Za-z0-9_])" + SECRET_KEY +
               r"[\"'`*\s]*(?:[:：=]|\bis\b|为|是)\s*[\"'`]*[^\s\"'`,}]+"),
    re.compile(r"(?im)^\s*[#*\-\"'` ]*" + SECRET_KEY +
               r"[\"'` ]*\s*\n\s*\S+"),
    re.compile(r"(?i)(?<![A-Za-z0-9_])(?:app[ _-]?secret|client[ _-]?secret|"
               r"api[ _-]?key|access[ _-]?(?:key|token)|refresh[ _-]?token|"
               r"secret[ _-]?key|密码|密钥|秘钥)[\"'`]*[ \t]+[\"'`]*"
               r"[A-Za-z0-9_+/=.-]{16,}"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"(?i)\b(?:https?|postgres(?:ql)?|mysql|redis)://"
               r"[^\s/:]+:[^\s/@]+@"),
]
SENSITIVE_NAMES = {
    ".git", ".jj", "node_modules", "subagents", ".ssh", ".aws", ".gnupg",
    ".secrets", "secrets", "credentials", "auth", "config", "__pycache__",
}
SENSITIVE_FILE = re.compile(
    r"(?i)^(?:\.?env(?:\..*)?|(?:auth|config|credentials?|secrets?|tokens?)"
    r"(?:\.(?:json|jsonl|ya?ml|toml|ini|conf|txt))?|id_(?:rsa|ed25519|ecdsa))$"
)
CONTEXT_TAGS = (
    "system-reminder", "system_reminder", "environment_context", "turn_aborted",
    "local-command-caveat", "local-command-stdout", "task-notification",
    "artifact-view-context", "permissions", "permissions_instructions",
    "user_instructions", "developer_instructions", "INSTRUCTIONS",
    "external_codex_apps_open_page", "codex_apps_open_page_instructions",
    "codex_apps_client_time_context", "session-mentions",
)
CONTEXT_BLOCK = re.compile(
    r"<(?P<tag>" + "|".join(CONTEXT_TAGS) + r")\b[^>]*>.*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
UNFINISHED_CONTEXT = re.compile(
    r"<(?:" + "|".join(CONTEXT_TAGS) + r")\b[^>]*>.*$",
    re.IGNORECASE | re.DOTALL,
)
SYNTHETIC_PREFIXES = (
    "This session is being continued from a previous conversation",
    "[Request interrupted", "<command-name>", "<command-message>",
    "<bash-input>", "<bash-stdout>", "<bash-stderr>",
)


def contains_secret(text, title=""):
    """Conservative pre-output check; not a guarantee of privacy or redaction.

    Call on the complete, untruncated body. A credential-like title also rejects
    the entire record. This function is usable by optional local export adapters.
    """
    if SECRET_TITLE.search(title or ""):
        return True
    # Export adapters may pass json.dumps(record); inspect escaped newlines too.
    text = text.replace("\\n", "\n").replace("\\r", "\n").replace("\\t", " ")
    for heading in re.findall(r"(?m)^\s*#{1,6}\s+(.+)$", text):
        if SECRET_TITLE.search(heading):
            return True
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def record_contains_secret(value):
    """Inspect a JSON-compatible record, including keys, titles, and raw strings."""
    if isinstance(value, dict):
        title = value.get("title")
        if isinstance(title, str) and contains_secret("", title=title):
            return True
        if contains_secret(json.dumps(value, ensure_ascii=False)):
            return True
        return any(record_contains_secret(item) for item in value.values())
    if isinstance(value, list):
        blocks = [item["text"] for item in value if isinstance(item, dict)
                  and isinstance(item.get("text"), str)]
        return contains_secret("\n".join(blocks)) or any(record_contains_secret(item) for item in value)
    return isinstance(value, str) and contains_secret(value)


def _sensitive_name(name):
    return (name.lower() in SENSITIVE_NAMES or name.lower().startswith(".env")
            or bool(SENSITIVE_FILE.fullmatch(name))
            or name.lower().endswith((".pem", ".key", ".p12", ".pfx")))


def _clean_text(text):
    if text.lstrip().startswith(SYNTHETIC_PREFIXES):
        return ""
    text = CONTEXT_BLOCK.sub("", text)
    text = UNFINISHED_CONTEXT.sub("", text)
    text = re.sub(r"(?m)^# AGENTS\.md instructions for .*\n?", "", text)
    return text.strip()


def _text_content(content):
    if isinstance(content, str):
        return _clean_text(content)
    if isinstance(content, list):
        return "\n".join(
            cleaned for item in content if isinstance(item, dict)
            and item.get("type") in ("text", "input_text", "output_text")
            and isinstance(item.get("text"), str)
            for cleaned in [_clean_text(item["text"])] if cleaned
        )
    return ""


def _parse_time(value):
    if isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(
                value / 1000 if abs(value) >= 100000000000 else value, timezone.utc
            )
        if isinstance(value, str) and value.strip():
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None
                    else parsed.astimezone(timezone.utc))
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def _files(root, kind, counts, errors):
    """Never follow symlinks, including a selected symlink root."""
    if any(_sensitive_name(part) for part in root.parts):
        counts["sensitive_paths_skipped"] += 1
        return
    try:
        symlink = root.is_symlink()
        exists = root.exists()
        regular_file = root.is_file()
    except OSError:
        errors.append({"source": kind, "code": "path_unreadable"})
        return
    if symlink:
        counts["symlinks_skipped"] += 1
        return
    if not exists:
        errors.append({"source": kind, "code": "path_unavailable"})
        return
    extensions = {".md", ".markdown"} if kind == "markdown" else {".json", ".jsonl", ".ndjson"}
    if regular_file:
        if root.suffix.lower() in extensions:
            yield root
        else:
            counts["unsupported_files_skipped"] += 1
        return
    def walk_error(_error):
        errors.append({"source": kind, "code": "directory_unreadable"})
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        allowed = []
        for name in sorted(dirs):
            candidate = Path(directory) / name
            if candidate.is_symlink():
                counts["symlinks_skipped"] += 1
            elif _sensitive_name(name):
                counts["sensitive_paths_skipped"] += 1
            else:
                allowed.append(name)
        dirs[:] = allowed
        for name in sorted(names):
            candidate = Path(directory) / name
            if candidate.is_symlink():
                counts["symlinks_skipped"] += 1
            elif _sensitive_name(name):
                counts["sensitive_paths_skipped"] += 1
            elif candidate.suffix.lower() in extensions:
                yield candidate


def _json_array_entries(text, start):
    decoder = json.JSONDecoder()
    position = start + 1
    while True:
        while position < len(text) and text[position] in " \t\r\n,":
            position += 1
        if position >= len(text) or text[position] == "]":
            return
        value, end = decoder.raw_decode(text, position)
        yield value, text.count("\n", 0, position) + 1
        position = end


def _document_entries(text):
    # Parse first so invalid documents never produce a partial valid-looking list.
    value = json.loads(text)
    start = len(text) - len(text.lstrip())
    if isinstance(value, list):
        yield from _json_array_entries(text, start)
    elif isinstance(value, dict) and isinstance(value.get("records"), list):
        decoder = json.JSONDecoder()
        position = start + 1
        while position < len(text):
            while text[position] in " \t\r\n,":
                position += 1
            key, position = decoder.raw_decode(text, position)
            while text[position] in " \t\r\n:":
                position += 1
            if key == "records":
                yield from _json_array_entries(text, position)
                return
            _, position = decoder.raw_decode(text, position)
    else:
        yield value, text.count("\n", 0, start) + 1


def _json_entries(path, kind, errors):
    try:
        with path.open(encoding="utf-8-sig") as handle:
            if path.suffix.lower() == ".json":
                try:
                    yield from _document_entries(handle.read())
                except (ValueError, IndexError):
                    errors.append({"source": kind, "code": "invalid_json"})
            else:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        yield json.loads(line), line_number
                    except ValueError:
                        errors.append({"source": kind, "code": "invalid_json"})
    except (OSError, UnicodeError):
        errors.append({"source": kind, "code": "file_unreadable"})


def _message(raw, kind):
    if not isinstance(raw, dict):
        return None
    origin = raw.get("origin")
    if (raw.get("isSidechain") or raw.get("isMeta") or raw.get("agentId")
            or (isinstance(origin, dict) and origin.get("kind") in ("agent", "internal"))):
        return None
    if kind == "claude":
        if raw.get("type") not in ("user", "assistant"):
            return None
        message = raw.get("message", {})
        if not isinstance(message, dict):
            return None
        return (raw["type"], _text_content(message.get("content")),
                raw.get("timestamp"), raw.get("uuid"), "claude")
    if kind == "codex":
        payload = raw.get("payload", {})
        if not isinstance(payload, dict):
            return None
        if raw.get("type") == "response_item" and payload.get("type") == "message":
            return (payload.get("role"), _text_content(payload.get("content")),
                    raw.get("timestamp"), payload.get("id"), "response")
        if raw.get("type") == "event_msg" and payload.get("type") in ("user_message", "agent_message"):
            role = "user" if payload["type"] == "user_message" else "assistant"
            return (role, _text_content(payload.get("message")), raw.get("timestamp"),
                    payload.get("id"), "event")
        return None
    return (raw.get("role", "user"), _text_content(raw.get("text")),
            raw.get("timestamp"), raw.get("id"), "json")


def collect(sources, days=30, limit=100, max_chars=1500, include_assistant=False, now=None):
    """Return a JSON-compatible report. Sources are (kind, explicit_path) pairs."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days) if days else None
    counts = Counter()
    errors = []
    candidates = []
    visited = set()
    for kind, selected in sources:
        root = Path(selected).expanduser().absolute()
        for path in _files(root, kind, counts, errors):
            file_key = (kind, str(path.resolve()))
            if file_key in visited:
                counts["duplicate_files_skipped"] += 1
                continue
            visited.add(file_key)
            if contains_secret(str(path), title=path.stem):
                counts["secret_records_skipped"] += 1
                continue
            counts["files_read"] += 1
            if kind == "markdown":
                try:
                    text = path.read_text(encoding="utf-8-sig")
                    edited = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                except (OSError, UnicodeError):
                    errors.append({"source": kind, "code": "file_unreadable"})
                    continue
                entries = [({"text": text, "role": "source"}, 1)]
            else:
                entries = _json_entries(path, kind, errors)
            session = str(path.resolve())
            subagent = False
            for raw, line in entries:
                if kind == "codex" and isinstance(raw, dict) and raw.get("type") == "session_meta":
                    payload = raw.get("payload", {})
                    if isinstance(payload, dict):
                        session = str(payload.get("id") or session)
                        source = payload.get("source")
                        subagent = (source == "subagent" or
                                    isinstance(source, dict) and "subagent" in source)
                    continue
                if subagent:
                    counts["non_user_records_skipped"] += 1
                    continue
                message = _message(raw, "json" if kind == "markdown" else kind)
                roles = ("user", "assistant", "source") if kind in ("json", "markdown") else ("user", "assistant")
                if not message or message[0] not in roles:
                    counts["non_user_records_skipped"] += 1
                    continue
                role, text, timestamp, native_id, variant = message
                if role == "assistant" and not include_assistant:
                    counts["assistant_records_skipped"] += 1
                    continue
                # Check raw data before cleaning or truncation can hide credentials.
                title = raw.get("title", "") if isinstance(raw.get("title"), str) else ""
                if record_contains_secret(raw) or contains_secret(text, title=title):
                    counts["secret_records_skipped"] += 1
                    continue
                if not text:
                    counts["empty_or_context_records_skipped"] += 1
                    continue
                parsed = _parse_time(timestamp)
                date = edited if kind == "markdown" else parsed
                if cutoff and date is None:
                    counts["undated_records_skipped"] += 1
                    continue
                if cutoff and date < cutoff:
                    counts["old_records_skipped"] += 1
                    continue
                if kind == "claude":
                    session = str(raw.get("sessionId") or session)
                scope = (kind, session)
                locator = "{}:{}".format(path.resolve(), line)
                identity = ((scope, str(native_id)) if native_id is not None
                            else (scope, role, _iso(parsed), text))
                digest = hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()[:24]
                record = {"id": kind + ":" + digest, "source": kind,
                          "locator": locator, "timestamp": _iso(parsed),
                          "role": role, "text": text}
                if kind == "markdown":
                    record["modified_at"] = _iso(edited)
                status = raw.get("status")
                if isinstance(status, str):
                    record["status"] = status[:100]
                candidates.append((date or datetime.min.replace(tzinfo=timezone.utc),
                                   record, scope, variant))
    candidates.sort(key=lambda item: (item[0], item[1]["locator"]), reverse=True)
    output = []
    seen_ids = set()
    mirrors = {}
    for date, record, scope, variant in candidates:
        mirror_key = (scope, record["role"], record["text"])
        previous = mirrors.get(mirror_key)
        mirrored = (record["source"] == "codex" and previous is not None
                    and variant != previous[1] and {variant, previous[1]} == {"event", "response"}
                    and abs((date - previous[0]).total_seconds()) <= 2)
        if record["id"] in seen_ids or mirrored:
            counts["duplicate_records_skipped"] += 1
            continue
        seen_ids.add(record["id"])
        mirrors[mirror_key] = (date, variant)
        output.append(record)
    counts["eligible_unique_records"] = len(output)
    counts["limited_records"] = max(0, len(output) - limit)
    output = output[:limit]
    for record in output:
        if len(record["text"]) > max_chars:
            record["text"] = record["text"][:max_chars]
            counts["truncated_records"] += 1
    counts["returned_records"] = len(output)
    return {"records": output, "summary": {
        "counts": dict(sorted(counts.items())), "errors": errors,
        "days": days, "limit": limit, "max_chars": max_chars,
        "include_assistant": include_assistant, "order": "newest_first",
        "message_dates": "message timestamp; naive timestamps assumed UTC; undated require --days 0",
        "markdown_dates": "modified_at is file edit time, used only for recency; timestamp is null",
        "privacy_notice": "Credential filters are incomplete. Review output before sharing.",
    }}


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise ValueError("invalid_arguments")


def main(argv=None):
    parser = _Parser(description=__doc__)
    for kind in ("claude", "codex", "markdown", "json"):
        parser.add_argument("--" + kind, action="append", default=[], metavar="PATH",
                            help="explicit file or directory; repeatable")
    parser.add_argument("--days", type=int, default=30, help="recency window; 0 includes undated/all dates")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-chars", type=int, default=1500)
    parser.add_argument("--include-assistant", action="store_true")
    try:
        args = parser.parse_args(argv)
        sources = [(kind, path) for kind in ("claude", "codex", "markdown", "json")
                   for path in getattr(args, kind)]
        if not sources or args.days < 0 or args.limit < 1 or args.max_chars < 1:
            raise ValueError("invalid_arguments")
    except ValueError:
        print(json.dumps({"records": [], "summary": {"errors": [{"code": "invalid_arguments"}]}}))
        return 2
    result = collect(sources, args.days, args.limit, args.max_chars, args.include_assistant)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
