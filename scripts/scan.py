#!/usr/bin/env python3
"""repo-world scanner: turns a codebase into world.json (districts, NPCs, roads, bosses, graveyard)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

SRC_EXT = {
    ".php", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".svelte", ".py",
    ".go", ".rb", ".java", ".kt", ".cs", ".rs", ".swift", ".dart",
}
IGNORE_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", "out", "coverage", ".next",
    ".nuxt", ".angular", ".svelte-kit", "storage", "cache", "__pycache__", ".venv",
    "venv", "env", "target", "bin", "obj", ".idea", ".vscode", "public", "tmp",
    ".turbo", ".cache", "lang", "fixtures", "__snapshots__", "Pods", ".gradle",
}
ROOT_PREFIXES = ("app/", "src/app/", "src/", "lib/", "resources/js/", "packages/", "apps/")
CONTAINERS = {
    "http", "components", "features", "modules", "pages", "domain", "domains",
    "app", "views", "routes", "packages", "apps", "services", "shared", "core",
}
GOD_LOC, GOD_METHODS = 450, 30
MAX_DISTRICTS = 16

ROLE_RULES = [  # case-sensitive on purpose: `Resources/` (API) != `resources/` (assets)
    ("test", r"(^|/)([Tt]ests?|__tests__|spec|e2e)/|\.(test|spec|cy)\.\w+$|Test\.php$"),
    ("migration", r"(^|/)(migrations|database|seeders|factories|Seeders|Factories)/"),
    ("controller", r"Controller\.\w+$|(^|/)controllers/"),
    ("model", r"(^|/)(Models|models|entities|Entities)/|\.(model|entity|schema)\.ts$"),
    ("middleware", r"(^|/)(Middleware|middleware|Policies|guards)/|Policy\.php$|\.(guard|interceptor)\.ts$"),
    ("job", r"(^|/)(Jobs|Listeners|Events|Observers|Notifications|Mail|Console|jobs|listeners|events)/"),
    ("service", r"Service\.\w+$|\.service\.ts$|(^|/)(Services|Actions|UseCases|services|actions|api)/"),
    ("request", r"(^|/)(Requests|Http/Resources|Dto|DTOs|dto|Rules)/|\.dto\.ts$"),
    ("component", r"\.component\.ts$|\.(tsx|jsx|vue|svelte)$|(^|/)(components|Livewire|View/Components)/"),
    ("store", r"(^|/)(store|stores|state|redux|slices)/|\.store\.ts$|Slice\.\w+$"),
    ("hook", r"(^|/)(hooks|composables)/|/use[A-Z]\w+\.\w+$"),
    ("route", r"(^|/)routes/|[Rr]outing|[Rr]outer"),
    ("config", r"(^|/)(config|Providers|bootstrap)/|\.config\.\w+$|Provider\.php$|\.module\.ts$"),
    ("util", r"(^|/)(utils?|helpers?|lib|support|Support|Helpers|Concerns|Traits|shared)/"),
]
ROLE_RE = [(r, re.compile(p)) for r, p in ROLE_RULES]

ENTITY_RES = {
    "php": re.compile(r"^\s*(?:abstract\s+|final\s+|readonly\s+)*(class|interface|trait|enum)\s+(\w+)", re.M),
    "js": re.compile(
        r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?(class|interface|function|const|type|enum)\s+(\w+)", re.M
    ),
    "py": re.compile(r"^(class|def)\s+(\w+)", re.M),
    "go": re.compile(r"^(type|func)\s+(?:\([^)]*\)\s*)?([A-Z]\w*)", re.M),
    "java": re.compile(r"^\s*(?:public\s+|abstract\s+|final\s+)*(class|interface|enum|record)\s+(\w+)", re.M),
    "rb": re.compile(r"^\s*(class|module)\s+([A-Z]\w*)", re.M),
}
METHOD_RES = {
    "php": re.compile(r"^\s*(?:public|protected|private)?\s*(?:static\s+)?function\s+(\w+)", re.M),
    "js": re.compile(
        r"^\s{2,}(?:public\s+|private\s+|protected\s+|static\s+|async\s+|readonly\s+)*([a-zA-Z_]\w*)\s*\([^;{]*\)\s*(?::\s*[^{=]+)?\{",
        re.M,
    ),
    "py": re.compile(r"^\s+def\s+(\w+)", re.M),
    "go": re.compile(r"^func\s+\([^)]*\)\s*(\w+)", re.M),
    "java": re.compile(r"^\s+(?:public|protected|private)\s+[\w<>\[\], ]+\s+(\w+)\s*\(", re.M),
    "rb": re.compile(r"^\s+def\s+(\w+)", re.M),
}
JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "constructor", "else"}
PHP_USE = re.compile(r"^use\s+([\w\\]+)(?:\s+as\s+\w+)?;", re.M)
JS_IMPORT = re.compile(r"""(?:import|export)[^'"`;]*?from\s*['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)""")
PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
ROUTE_RE = re.compile(r"Route::(get|post|put|patch|delete|resource|apiResource)\s*\(\s*['\"]([^'\"]*)['\"]", re.I)


def lang_of(ext: str) -> str:
    return {
        ".php": "php", ".py": "py", ".go": "go", ".rb": "rb", ".java": "java", ".kt": "java", ".cs": "java",
    }.get(ext, "js")


def role_of(path: str) -> str:
    if path.endswith(".blade.php"):
        return "view"
    for role, rx in ROLE_RE:
        if rx.search(path):
            return role
    return "other"


def district_key(rel: str) -> str:
    p = rel
    for pre in ROOT_PREFIXES:
        if p.startswith(pre):
            p = p[len(pre):]
            break
    parts = p.split("/")[:-1]
    if not parts:
        return "Town Square"
    if parts[0].lower() in CONTAINERS and len(parts) > 1:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60, check=False
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def walk(repo: Path, max_files: int, max_bytes: int):
    out = []
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS and not d.startswith("."))
        for f in sorted(files):
            ext = Path(f).suffix.lower()
            if ext not in SRC_EXT or f.endswith((".min.js", ".d.ts")):
                continue
            full = Path(root) / f
            try:
                if full.stat().st_size > max_bytes:
                    continue
            except OSError:
                continue
            out.append(full)
    if len(out) > max_files:  # keep the largest files: they shape the city
        out.sort(key=lambda p: p.stat().st_size, reverse=True)
        out = sorted(out[:max_files])
    return out


def parse_file(full: Path, rel: str) -> dict:
    text = full.read_text(encoding="utf-8", errors="ignore")
    ext = full.suffix.lower()
    lang = lang_of(ext)
    loc = sum(1 for line in text.splitlines() if line.strip())
    entities = []
    rx = ENTITY_RES.get(lang)
    if rx:
        for kind, name in rx.findall(text):
            if lang == "py" and kind == "def":
                continue
            if lang == "js" and kind in {"const", "function"} and not name[:1].isupper():
                continue
            entities.append({"name": name, "kind": kind})
    if not entities and ext in {".vue", ".svelte"}:
        entities.append({"name": full.stem, "kind": "component"})
    deco = re.search(r"@(Component|Injectable|NgModule|Directive|Pipe)\(", text)
    if deco and entities:
        entities[0]["kind"] = deco.group(1).lower()
    methods = []
    mrx = METHOD_RES.get(lang)
    if mrx:
        seen = set()
        for m in mrx.findall(text):
            if m not in seen and m not in JS_KEYWORDS and not m.startswith("__"):
                seen.add(m)
                methods.append(m)
    imports = []
    if lang == "php":
        imports = [("php", u) for u in PHP_USE.findall(text)]
    elif lang == "py":
        imports = [("py", a or b) for a, b in PY_IMPORT.findall(text)]
    else:
        imports = [("js", a or b) for a, b in JS_IMPORT.findall(text)]
    return {
        "path": rel,
        "loc": loc,
        "role": role_of(rel),
        "entities": entities[:6],
        "methods": methods[:40],
        "methodCount": len(methods),
        "todos": len(TODO_RE.findall(text)),
        "_imports": imports,
    }


def resolve_imports(files: dict[str, dict], repo: Path) -> list[tuple[str, str]]:
    by_class: dict[str, str] = {}
    by_stem: dict[str, list[str]] = defaultdict(list)
    by_noext: dict[str, str] = {}
    for p, f in files.items():
        for e in f["entities"]:
            by_class.setdefault(e["name"], p)
        stem = Path(p).stem.split(".")[0]
        by_stem[stem].append(p)
        noext = str(Path(p).with_suffix(""))
        by_noext[noext] = p
        if noext.endswith("/index"):
            by_noext[noext[: -len("/index")]] = p
    aliases = [("@/", ["src/", "resources/js/", "app/"]), ("~/", ["src/", ""]), ("src/", ["src/"])]
    edges = set()
    for p, f in files.items():
        base = Path(p).parent
        for kind, spec in f.pop("_imports"):
            target = None
            if kind == "php":
                target = by_class.get(spec.split("\\")[-1])
            elif kind == "py":
                cand = spec.replace(".", "/")
                target = by_noext.get(cand) or by_noext.get(f"src/{cand}")
            else:
                cands = []
                if spec.startswith("."):
                    cands.append(os.path.normpath(str(base / spec)))
                else:
                    for pre, reps in aliases:
                        if spec.startswith(pre):
                            cands += [r + spec[len(pre):] for r in reps]
                for c in cands:
                    c = str(Path(c).with_suffix("")) if Path(c).suffix in SRC_EXT else c
                    target = by_noext.get(c)
                    if target:
                        break
            if target and target != p:
                edges.add((p, target))
    return sorted(edges)


def find_cycles(nodes: list[str], edges: list[tuple[str, str]], limit: int = 8) -> list[list[str]]:
    """Tarjan SCC, iterative."""
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
    index, low, on, stack, sccs, counter = {}, {}, set(), [], [], [0]
    for start in nodes:
        if start in index:
            continue
        work = [(start, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter[0]
                counter[0] += 1
                stack.append(v)
                on.add(v)
            recurse = False
            for j in range(i, len(adj[v])):
                w = adj[v][j]
                if w not in index:
                    work.append((v, j + 1))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    sccs.append(sorted(comp))
            if work:
                u = work[-1][0]
                low[u] = min(low[u], low[v])
    sccs.sort(key=len)
    return sccs[:limit]


def git_data(repo: Path, src_paths: set[str]) -> dict:
    top = git(repo, "rev-parse", "--show-toplevel").strip()
    if not top:
        return {"commits": 0, "heroes": [], "graveyard": [], "churn": {}, "since": None}
    prefix = repo.relative_to(Path(top).resolve()).as_posix() if repo != Path(top).resolve() else ""
    pre = prefix + "/" if prefix and prefix != "." else ""
    rel = lambda p: p[len(pre):] if pre and p.startswith(pre) else (p if not pre else None)  # noqa: E731
    authors = Counter(a for a in git(repo, "log", "--no-merges", "--format=%an", "--", ".").splitlines() if a)
    total = sum(authors.values())
    first = git(repo, "log", "--reverse", "--format=%ad", "--date=short", "--", ".").splitlines()
    churn = Counter(
        r for p in git(repo, "log", "--no-merges", "-n", "3000", "--name-only", "--format=", "--", ".").splitlines()
        if (r := rel(p)) in src_paths
    )
    graveyard, meta = [], None
    for raw in git(
        repo, "log", "--diff-filter=D", "-n", "400", "--name-only", "--format=@@%h|%an|%ad|%s", "--date=short",
        "--", ".",
    ).splitlines():
        line = raw if raw.startswith("@@") else rel(raw)
        if not line:
            continue
        if line.startswith("@@"):
            meta = line[2:].split("|", 3)
        elif meta and Path(line).suffix.lower() in SRC_EXT and len(graveyard) < 24:
            if not any(seg in IGNORE_DIRS for seg in line.split("/")):
                graveyard.append({"path": line, "sha": meta[0], "author": meta[1], "date": meta[2], "msg": meta[3][:90]})
    return {
        "commits": total,
        "since": first[0] if first else None,
        "heroes": [{"name": n, "commits": c} for n, c in authors.most_common(8)],
        "graveyard": graveyard,
        "churn": dict(churn),
    }


def detect_framework(repo: Path) -> str:
    pkg = repo / "package.json"
    deps = ""
    if pkg.exists():
        try:
            d = json.loads(pkg.read_text(encoding="utf-8"))
            deps = " ".join({**d.get("dependencies", {}), **d.get("devDependencies", {})})
        except (ValueError, OSError):
            pass
    if (repo / "artisan").exists():
        return "Laravel" + (" + Vue" if "vue" in deps else " + React" if "react" in deps else "")
    for key, name in (("@angular/core", "Angular"), ("next", "Next.js"), ("nuxt", "Nuxt"), ("react", "React"),
                      ("vue", "Vue"), ("svelte", "Svelte"), ("@nestjs/core", "NestJS"), ("express", "Express")):
        if re.search(rf"(^|\s){re.escape(key)}(\s|$)", deps):
            return name
    if (repo / "manage.py").exists():
        return "Django"
    if (repo / "go.mod").exists():
        return "Go"
    if (repo / "Gemfile").exists():
        return "Ruby"
    if (repo / "pyproject.toml").exists() or (repo / "setup.py").exists():
        return "Python"
    return "Code"


def laravel_routes(repo: Path) -> list[dict]:
    out = []
    for rf in ("routes/web.php", "routes/api.php"):
        fp = repo / rf
        if fp.exists():
            for verb, uri in ROUTE_RE.findall(fp.read_text(encoding="utf-8", errors="ignore")):
                out.append({"verb": verb.upper(), "uri": "/" + uri.lstrip("/"), "file": rf})
    return out[:80]


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan a repo into world.json for repo-world")
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("-o", "--out", default="world.json")
    ap.add_argument("--max-files", type=int, default=600)
    ap.add_argument("--max-bytes", type=int, default=400_000)
    a = ap.parse_args()
    for s in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    repo = Path(a.repo).resolve()
    if not repo.is_dir():
        print(f"not a directory: {repo}", file=sys.stderr)
        return 1
    paths = walk(repo, a.max_files, a.max_bytes)
    if not paths:
        print("no source files found", file=sys.stderr)
        return 1

    files = {}
    for full in paths:
        rel = full.relative_to(repo).as_posix()
        files[rel] = parse_file(full, rel)

    edges = resolve_imports(files, repo)
    indeg, outdeg = Counter(b for _, b in edges), Counter(a_ for a_, _ in edges)
    g = git_data(repo, set(files))
    churn = g.pop("churn")
    hot_cut = sorted(churn.values(), reverse=True)[max(0, len(churn) // 16 - 1)] if churn else 10**9

    groups: dict[str, list[str]] = defaultdict(list)
    for p in files:
        groups[district_key(p)].append(p)
    ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    keep = dict(ranked[: MAX_DISTRICTS - 1])
    rest = [p for k, v in ranked[MAX_DISTRICTS - 1:] for p in v]
    small = [k for k, v in keep.items() if len(v) < 2 and k != "Town Square"]
    for k in small:
        rest += keep.pop(k)
    if rest:
        keep.setdefault("Outskirts", []).extend(rest)

    district_of, districts = {}, []
    for i, (name, plist) in enumerate(sorted(keep.items(), key=lambda kv: -len(kv[1]))):
        did = f"d{i}"
        flist = []
        for p in sorted(plist, key=lambda x: (-indeg[x], x)):
            f = files[p]
            district_of[p] = did
            f["in"], f["out"] = indeg[p], outdeg[p]
            f["churn"] = churn.get(p, 0)
            f["hot"] = churn.get(p, 0) >= hot_cut and churn.get(p, 0) >= 5
            f["boss"] = f["loc"] >= GOD_LOC or f["methodCount"] >= GOD_METHODS
            f["deps"] = [b for x, b in edges if x == p][:12]
            f["usedBy"] = [x for x, b in edges if b == p][:12]
            flist.append(f)
        roles = Counter(f["role"] for f in flist)
        districts.append({
            "id": did, "name": name, "files": flist,
            "loc": sum(f["loc"] for f in flist), "mainRole": roles.most_common(1)[0][0],
        })

    dedges = Counter()
    for x, y in edges:
        dx, dy = district_of.get(x), district_of.get(y)
        if dx and dy and dx != dy:
            dedges[(dx, dy)] += 1

    world = {
        "version": 1,
        "meta": {
            "name": repo.name, "framework": detect_framework(repo), "files": len(files),
            "loc": sum(f["loc"] for f in files.values()), "commits": g["commits"], "since": g["since"],
            "bosses": sum(1 for f in files.values() if f.get("boss")),
            "todos": sum(f["todos"] for f in files.values()),
        },
        "districts": districts,
        "roads": [{"from": a_, "to": b, "w": w} for (a_, b), w in dedges.most_common(60)],
        "cycles": find_cycles(list(files), edges),
        "heroes": g["heroes"],
        "graveyard": g["graveyard"],
        "routes": laravel_routes(repo),
    }
    Path(a.out).write_text(json.dumps(world, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    m = world["meta"]
    print(
        f"✓ {m['name']} ({m['framework']}): {m['files']} files, {m['loc']} LOC, {len(districts)} districts, "
        f"{len(edges)} imports, {m['bosses']} bosses, {len(world['cycles'])} cycles, "
        f"{len(world['graveyard'])} graves → {a.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
