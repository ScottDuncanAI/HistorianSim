import subprocess, sys, zipfile
from pathlib import Path

repo = Path(sys.argv[1])
out = Path(sys.argv[2])
files = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True).stdout.split("\n")
skill = ".claude/skills/simulate/"
src_keep = ("pyproject.toml", "README.md", "LICENSE", "CLAUDE.md")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    n = 0
    for f in filter(None, files):
        if f.startswith(skill):
            arc = "simulate/" + f[len(skill):]
        elif f.startswith("src/") or f in src_keep:
            arc = "simulate/historiansim-src/" + f
        else:
            continue
        z.write(repo / f, arc)
        n += 1
print(n, "files", out.stat().st_size // 1024, "KB")
