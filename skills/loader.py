"""Skills 加载器（Day7）。

Skill 与 Tool 的区别：
  - Tool 是一次函数调用（read 一个文件）。
  - Skill 是一包"领域知识 + 操作流程 + 可选脚本/资源"，用一个 SKILL.md 描述，
    在合适的时候被加载进上下文，告诉模型"面对这类任务该怎么一步步做"。

SKILL.md 结构（约定）：
  ---
  name: pdf-report
  description: 一句话说明何时该用这个 skill（用于召回判断）
  enabled: true
  ---
  正文：步骤、注意事项、可调用的脚本路径、示例。

启用/禁用：
  - frontmatter 中的 enabled 字段控制默认状态（缺省为 true）。
  - 交互界面可通过 /skill-toggle 切换，直接写回 SKILL.md。
  - load_skills() 只返回 enabled 的 skill。
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path
    enabled: bool = True


def parse_skill_md(text: str, path: Path) -> Skill:
    name = description = ""
    enabled = True
    body = text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        try:
            import yaml

            meta = yaml.safe_load(fm) or {}
            name = meta.get("name", "")
            description = meta.get("description", "")
            enabled = meta.get("enabled", True)
        except ModuleNotFoundError:
            for line in fm.splitlines():
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                value = value.strip().strip("\"'")
                if key.strip() == "name":
                    name = value
                elif key.strip() == "description":
                    description = value
                elif key.strip() == "enabled":
                    enabled = value.lower() in ("true", "yes", "1")
    return Skill(name=name, description=description, body=body.strip(),
                 path=path, enabled=enabled)


def load_skills(root: str = "skills") -> list[Skill]:
    """扫描 root 下所有 SKILL.md，只返回启用的 skill。"""
    skills: list[Skill] = []
    for md in Path(root).glob("*/SKILL.md"):
        skill = parse_skill_md(md.read_text(encoding="utf-8"), md)
        if skill.enabled:
            skills.append(skill)
    return skills


def load_all_skills(root: str = "skills") -> list[Skill]:
    """扫描 root 下所有 SKILL.md，含禁用的（供 REPL /skills 命令用）。"""
    skills: list[Skill] = []
    for md in Path(root).glob("*/SKILL.md"):
        skills.append(parse_skill_md(md.read_text(encoding="utf-8"), md))
    return skills


def load_skill_body(name: str, root: str = "skills") -> str | None:
    """按 skill 名称查找并返回其正文（供 invoke_skill 工具使用）。
    返回 None 表示未找到或 skill 已禁用。
    """
    for md in Path(root).glob("*/SKILL.md"):
        skill = parse_skill_md(md.read_text(encoding="utf-8"), md)
        if skill.name == name:
            if not skill.enabled:
                return None
            return skill.body
    return None


def toggle_skill(name: str, root: str = "skills") -> tuple[bool, str]:
    """切换 skill 的启用/禁用状态，写回 SKILL.md。
    返回 (new_enabled: bool, message: str)。
    """
    for md in Path(root).glob("*/SKILL.md"):
        skill = parse_skill_md(md.read_text(encoding="utf-8"), md)
        if skill.name == name:
            text = md.read_text(encoding="utf-8")
            new_enabled = not skill.enabled
            new_value = "true" if new_enabled else "false"

            # 替换 frontmatter 中的 enabled 字段
            if "\nenabled:" in text or "\nenabled :" in text:
                import re
                text = re.sub(
                    r"(\n\s*enabled\s*:\s*)(true|false|yes|no|1|0)",
                    rf"\g<1>{new_value}",
                    text, count=1,
                )
            else:
                # frontmatter 中没有 enabled 字段，追加
                text = text.replace("---", f"enabled: {new_value}\n---", 1)

            md.write_text(text, encoding="utf-8")
            status = "启用" if new_enabled else "禁用"
            return new_enabled, f"Skill '{name}' 已{status}（重启后生效）。"
    return False, f"未找到 skill：{name}"


def skills_catalog(skills: list[Skill]) -> str:
    """生成给模型看的可用 skill 清单（name + description），用于按需召回。"""
    return "\n".join(f"- {s.name}: {s.description}（{s.path.as_posix()}）" for s in skills)
