import json
from pathlib import Path


class Memory:
    """纯文本记忆（MEMORY.md）：追加写、全量召回。"""

    def __init__(self, path="MEMORY.md"):
        self.path = Path(path)

    def write(self, note: str):
        """写入一条记忆（追加落盘 = 持久化）。"""
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("- " + note.strip() + "\n")

    def recall(self, query: str = "") -> str:
        """召回：最简版本 = 读回全部（策略 A）。"""
        return self.path.read_text(encoding="utf-8") if self.path.exists() else ""


class KVMemory:
    """结构化键值记忆（memory.json）：支持按 key 覆盖更新与删除（讲义 §4.3/§4.4）。"""

    def __init__(self, path="memory.json"):
        self.path = Path(path)
        self.data: dict[str, str] = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists()
            else {}
        )

    def _save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def remember(self, key: str, value: str) -> str:
        """写入或更新一条键值记忆。"""
        self.data[key] = value
        self._save()
        return f"已记住：{key} = {value}"

    def forget(self, key: str) -> str:
        """删除一条键值记忆。"""
        if key in self.data:
            self.data.pop(key)
            self._save()
            return f"已遗忘：{key}"
        return f"键 '{key}' 不存在，无需遗忘。"

    def recall(self) -> str:
        """召回所有 KV 记忆，渲染为 Markdown 列表。"""
        if not self.data:
            return ""
        lines = [f"- {k}：{v}" for k, v in self.data.items()]
        return "\n".join(lines)


def recall_all(mem_path="MEMORY.md", kv_path="memory.json") -> str:
    """合并召回：纯文本记忆 + KV 记忆，用于注入 system prompt。"""
    parts = []
    text = Memory(mem_path).recall()
    if text.strip():
        parts.append(text.strip())
    kv = KVMemory(kv_path).recall()
    if kv.strip():
        parts.append(kv.strip())
    return "\n".join(parts)