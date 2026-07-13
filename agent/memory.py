from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path


_META_RE = re.compile(
    r"^(?P<note>.*?)\s*<!-- memory:id=(?P<id>[^;]+);created=(?P<created>[0-9.]+);"
    r"updated=(?P<updated>[0-9.]+);expires=(?P<expires>[0-9.]*) -->$"
)


def _clean(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label}不能为空")
    return value


def _expiry(ttl_seconds: float | None, current: float | None = None) -> float | None:
    if ttl_seconds is None:
        return None
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds 必须大于 0")
    return (time.time() if current is None else current) + ttl_seconds


def _memory_id(note: str) -> str:
    normalized = " ".join(note.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


@dataclass
class TextEntry:
    id: str
    note: str
    created_at: float
    updated_at: float
    expires_at: float | None = None

    def expired(self, current: float) -> bool:
        return self.expires_at is not None and self.expires_at <= current


class Memory:
    """纯文本项目记忆：去重、精确更新/删除、TTL 与容量淘汰。"""

    def __init__(self, path="MEMORY.md", max_entries: int = 100):
        if max_entries <= 0:
            raise ValueError("max_entries 必须大于 0")
        self.path = Path(path)
        self.max_entries = max_entries

    def _load(self) -> list[TextEntry]:
        if not self.path.exists():
            return []
        fallback_time = self.path.stat().st_mtime
        entries: list[TextEntry] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line.startswith("- "):
                continue
            body = line[2:].strip()
            match = _META_RE.match(body)
            if match:
                expires = match.group("expires")
                entries.append(TextEntry(
                    id=match.group("id"),
                    note=match.group("note").strip(),
                    created_at=float(match.group("created")),
                    updated_at=float(match.group("updated")),
                    expires_at=float(expires) if expires else None,
                ))
            else:
                entries.append(TextEntry(
                    id=_memory_id(body), note=body,
                    created_at=fallback_time, updated_at=fallback_time,
                ))
        return entries

    def _save(self, entries: list[TextEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for entry in entries:
            expires = "" if entry.expires_at is None else str(entry.expires_at)
            lines.append(
                f"- {entry.note} <!-- memory:id={entry.id};created={entry.created_at};"
                f"updated={entry.updated_at};expires={expires} -->"
            )
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _active(self) -> tuple[list[TextEntry], int]:
        entries = self._load()
        current = time.time()
        active = [entry for entry in entries if not entry.expired(current)]
        return active, len(entries) - len(active)

    def write(self, note: str, ttl_seconds: float | None = None) -> str:
        """新增记忆；完全相同的内容不会重复写入。"""
        note = _clean(note, "记忆内容")
        entries, expired = self._active()
        normalized = " ".join(note.casefold().split())
        for entry in entries:
            if " ".join(entry.note.casefold().split()) == normalized:
                if expired:
                    self._save(entries)
                return f"记忆已存在，未重复写入：{entry.id}"

        current = time.time()
        entry = TextEntry(
            id=_memory_id(note), note=note, created_at=current, updated_at=current,
            expires_at=_expiry(ttl_seconds, current),
        )
        entries.append(entry)
        evicted = max(0, len(entries) - self.max_entries)
        if evicted:
            entries = sorted(entries, key=lambda item: item.updated_at)[evicted:]
        self._save(entries)
        suffix = f"；清理过期 {expired} 条" if expired else ""
        suffix += f"；容量淘汰 {evicted} 条" if evicted else ""
        return f"已记住：{entry.id} - {note}{suffix}"

    def update(self, selector: str, new_note: str,
               ttl_seconds: float | None = None) -> str:
        """按记忆 ID 或完整原文更新一条纯文本记忆。"""
        selector = _clean(selector, "记忆选择器")
        new_note = _clean(new_note, "新记忆内容")
        entries, _ = self._active()
        target = next((e for e in entries if e.id == selector or e.note == selector), None)
        if target is None:
            return f"未找到纯文本记忆：{selector}"
        duplicate = next((e for e in entries if e is not target and e.note == new_note), None)
        if duplicate:
            return f"更新冲突：相同内容已存在于 {duplicate.id}"
        old_note = target.note
        target.note = new_note
        target.updated_at = time.time()
        if ttl_seconds is not None:
            target.expires_at = _expiry(ttl_seconds, target.updated_at)
        self._save(entries)
        return f"已更新：{target.id}；{old_note} -> {new_note}"

    def delete(self, selector: str) -> str:
        """按记忆 ID 或完整原文删除一条纯文本记忆。"""
        selector = _clean(selector, "记忆选择器")
        entries, _ = self._active()
        kept = [e for e in entries if e.id != selector and e.note != selector]
        if len(kept) == len(entries):
            return f"未找到纯文本记忆：{selector}"
        self._save(kept)
        return f"已删除纯文本记忆：{selector}"

    def recall(self, query: str = "") -> str:
        """召回全部有效记忆；同时清除已经到期的条目。"""
        entries, expired = self._active()
        if expired:
            self._save(entries)
        return "\n".join(f"- [{entry.id}] {entry.note}" for entry in entries)


class KVMemory:
    """结构化键值记忆：精确更新/删除、冲突提示、TTL 与容量淘汰。"""

    VERSION = 2

    def __init__(self, path="memory.json", max_entries: int = 100):
        if max_entries <= 0:
            raise ValueError("max_entries 必须大于 0")
        self.path = Path(path)
        self.max_entries = max_entries
        self.entries = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("memory.json 顶层必须是对象")
        if raw.get("version") == self.VERSION and isinstance(raw.get("entries"), dict):
            return raw["entries"]

        # 兼容旧版 {"key": "value"}；首次修改时自动升级为 v2。
        current = self.path.stat().st_mtime
        return {
            str(key): {
                "value": str(value), "created_at": current,
                "updated_at": current, "expires_at": None,
            }
            for key, value in raw.items()
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": self.VERSION, "entries": self.entries}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _prune(self) -> tuple[int, int]:
        current = time.time()
        expired_keys = [
            key for key, entry in self.entries.items()
            if entry.get("expires_at") is not None and entry["expires_at"] <= current
        ]
        for key in expired_keys:
            self.entries.pop(key)

        evicted = max(0, len(self.entries) - self.max_entries)
        if evicted:
            oldest = sorted(
                self.entries,
                key=lambda key: self.entries[key].get("updated_at", 0),
            )[:evicted]
            for key in oldest:
                self.entries.pop(key)
        return len(expired_keys), evicted

    def remember(self, key: str, value: str,
                 ttl_seconds: float | None = None) -> str:
        """新增或更新键值；同 key 不同 value 会明确报告冲突。"""
        key = _clean(key, "记忆 key")
        value = _clean(value, "记忆 value")
        self._prune()
        current = time.time()
        old = self.entries.get(key)
        if old and old.get("value") == value:
            if ttl_seconds is not None:
                old["expires_at"] = _expiry(ttl_seconds, current)
                old["updated_at"] = current
                self._save()
                return f"记忆内容未变化，已刷新 TTL：{key} = {value}"
            return f"记忆已存在，未重复写入：{key} = {value}"

        self.entries[key] = {
            "value": value,
            "created_at": old.get("created_at", current) if old else current,
            "updated_at": current,
            "expires_at": (
                _expiry(ttl_seconds, current) if ttl_seconds is not None
                else (old.get("expires_at") if old else None)
            ),
        }
        _, evicted = self._prune()
        self._save()
        if old:
            return f"检测到冲突并已更新：{key}；{old.get('value')} -> {value}"
        suffix = f"；容量淘汰 {evicted} 条" if evicted else ""
        return f"已记住：{key} = {value}{suffix}"

    def forget(self, key: str) -> str:
        """删除一条键值记忆。"""
        key = _clean(key, "记忆 key")
        self._prune()
        if key in self.entries:
            self.entries.pop(key)
            self._save()
            return f"已遗忘：{key}"
        return f"键 '{key}' 不存在，无需遗忘。"

    def recall(self) -> str:
        """召回所有有效 KV 记忆，并清理过期或超出容量的条目。"""
        expired, evicted = self._prune()
        if expired or evicted:
            self._save()
        return "\n".join(
            f"- {key}：{entry.get('value', '')}" for key, entry in self.entries.items()
        )


def recall_all(mem_path="MEMORY.md", kv_path="memory.json") -> str:
    """合并召回纯文本记忆与 KV 记忆，用于注入 system prompt。"""
    parts = []
    text = Memory(mem_path).recall()
    if text.strip():
        parts.append(text.strip())
    kv = KVMemory(kv_path).recall()
    if kv.strip():
        parts.append(kv.strip())
    return "\n".join(parts)
