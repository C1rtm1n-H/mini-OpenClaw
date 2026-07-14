from pathlib import Path

READONLY = {"read", "grep", "glob"}
WRITE    = {"write", "edit"}
EXEC     = {"bash", "web_fetch"}
META     = {"remember", "forget", "todo_write", "update_todo", "invoke_skill"}
# META 只操作项目记忆、进程内待办或 skill 加载，不执行外部命令，也不改用户代码。

def check(tool: str, args: dict, workdir: Path) -> str:
    """返回 'allow' / 'confirm' / 'deny'。"""
    if tool in READONLY:
        # 越界读取一样要拦：注入诱导"读 ~/.ssh/id_rsa"这类请求不能靠工具本身兜底。
        return "deny" if _escapes_workdir(args.get("path", "."), workdir) else "allow"
    if tool in META:
        return "allow"            # remember 等元操作只写项目约定文件，安全可控
    if tool == "pdf_extract":
        source = args.get("path", "")
        output = args.get("output_path", "")
        if _escapes_workdir(source, workdir) or (output and _escapes_workdir(output, workdir)):
            return "deny"
        # 已有缓存且未请求覆盖时，pdf_extract 只检查并复用，不发生写入。
        source_path = Path(source)
        if not source_path.is_absolute():
            source_path = workdir / source_path
        target = Path(output) if output else source_path.with_suffix(".txt")
        if output and not target.is_absolute():
            target = workdir / target
        if target.exists() and not args.get("overwrite", False):
            return "allow"
        return "confirm"
    if tool in WRITE:
        # 限制在工作目录内，越界直接拒绝
        return "deny" if _escapes_workdir(args.get("path", ""), workdir) else "confirm"
    if tool in EXEC:
        return "confirm"          # 执行/外传一律先确认（沙箱在步骤 2）
    return "confirm"              # 未知工具：保守，先问


def _escapes_workdir(path: str, workdir: Path) -> bool:
    """路径（展开 ~ 后）解析是否落在 workdir 之外。"""
    if not path:
        return False
    p = Path(path).expanduser()
    root = workdir.resolve()
    target = p.resolve() if p.is_absolute() else (root / p).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return True
    return False
