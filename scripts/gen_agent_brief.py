#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_agent_brief.py — deterministic generator for devdocs/AGENT_BRIEF.md

Design (see agent definitions cto.md / scribe.md):
  - AGENT_BRIEF.md = single source of truth for agent cold-start facts.
  - FACT sections are GENERATED from code (between GEN markers) — never hand-written.
  - NARRATIVE sections are HAND-maintained by Scribe (between HAND markers) — generator preserves them.
  - Every fact carries provenance (source file + hash) so agents can spot-check cheaply.
  - Stale rule: git HEAD sha != recorded sha, OR any source-file hash changed.

Usage:
  ./venv/bin/python scripts/gen_agent_brief.py            # regenerate GEN sections
  ./venv/bin/python scripts/gen_agent_brief.py --check    # exit 1 if stale (for CI/CTO Phase 0)
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIEF_PATH = os.path.join(ROOT, "devdocs", "AGENT_BRIEF.md")

# section -> list of source files it is derived from (relative to repo root)
SECTION_SOURCES = {
    "topology":   ["graph/workflow.py"],
    "state":      ["state/schema.py"],
    "routing":    ["agents/supervisor.py"],
    "llm_points": ["agents", "services"],
    "api":        ["api"],
    "db":         ["services", "agents", "api"],
}


def read(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def git_sha():
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL
        )
        return out.decode().strip()[:12]
    except Exception:
        return "UNKNOWN"


def file_hash(rel):
    p = os.path.join(ROOT, rel)
    if os.path.isdir(p):
        # aggregate hash of all .py files in dir (stable order)
        h = hashlib.sha256()
        for fn in sorted(os.listdir(p)):
            if fn.endswith(".py") and not fn.startswith("__"):
                data = read(os.path.join(rel, fn))
                if data:
                    h.update(fn.encode())
                    h.update(data.encode("utf-8", "replace"))
        return h.hexdigest()[:10]
    data = read(rel)
    if data is None:
        return "MISSING"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:10]


def listdir_files(base_rel, exts=(".py",)):
    base = os.path.join(ROOT, base_rel)
    out = []
    if not os.path.isdir(base):
        return out
    for fn in sorted(os.listdir(base)):
        if fn.endswith(exts) and not fn.startswith("__"):
            out.append(os.path.join(base_rel, fn))
    return out


# ---------------------------------------------------------------- extraction

def extract_topology():
    """Parse StateGraph build: add_node / add_edge / add_conditional_edges."""
    src = read("graph/workflow.py")
    if src is None:
        return ["UNVERIFIED: graph/workflow.py not found"]
    nodes = re.findall(r'add_node\(\s*"([^"]+)"\s*,\s*([\w.]+)', src)
    edges = re.findall(r'add_edge\(\s*"([^"]+)"\s*,\s*"([^"]+)"', src)
    conds = re.findall(r'add_conditional_edges\(\s*"([^"]+)"', src)
    lines = ["nodes (%d):" % len(nodes)]
    lines += ["  %s -> %s" % (n, impl) for n, impl in nodes]
    lines.append("conditional edges from: %s" % (", ".join(conds) if conds else "-"))
    lines.append("static edges (%d):" % len(edges))
    lines += ["  %s -> %s" % e for e in edges]
    if not nodes:
        lines.append("UNVERIFIED: 0 nodes extracted")
    return lines


def extract_state():
    """Parse AgentState TypedDict fields + reducers."""
    src = read("state/schema.py")
    if src is None:
        return ["UNVERIFIED: state/schema.py not found"]
    m = re.search(r"class\s+AgentState\s*\(TypedDict\):(.*?)(?=\nclass |\Z)", src, re.S)
    if not m:
        return ["UNVERIFIED: AgentState class not found"]
    lines, n_fields, n_reducers = [], 0, 0
    for raw in m.group(1).splitlines():
        line = raw.strip()
        fm = re.match(r"^(\w+)\s*:\s*(.+?)$", line)
        if not fm or line.startswith("#"):
            continue
        name = fm.group(1)
        rest = fm.group(2).strip()
        # split trailing inline comment at first " #" (types never contain '#')
        comment = ""
        hidx = rest.find("#")
        if hidx != -1:
            comment = " — " + rest[hidx + 1 :].strip()
            rest = rest[:hidx].strip().rstrip(",")
        typ = rest.rstrip(",").strip()
        reducer = ""
        rm = re.match(r"Annotated\[(.+?),\s*([\w.]+)\]", typ)
        if rm:
            reducer = " [reducer=%s]" % rm.group(2)
            n_reducers += 1
        lines.append("  %s: %s%s%s" % (name, typ, reducer, comment))
        n_fields += 1
    out = ["AgentState fields: %d (with reducer: %d)" % (n_fields, n_reducers)]
    out += lines
    if n_fields == 0:
        out.append("UNVERIFIED: 0 fields extracted")
    return out


def extract_routing():
    """Extract module-level keyword-routing constants from supervisor.py."""
    src = read("agents/supervisor.py")
    if src is None:
        return ["UNVERIFIED: agents/supervisor.py not found"]
    out = []
    for cm in re.finditer(r"^(_?[A-Z][A-Z0-9_]+)\s*=\s*\((.*?)^\s*\)", src, re.S | re.M):
        name, body = cm.group(1), cm.group(2)
        kws = []
        for kw in re.findall(r'["\']([^"\']{2,})["\']', body):
            kw = kw.strip()
            if not kw or "\n" in kw or len(kw) > 60:
                continue
            if any(t in kw for t in ("=", "{", "}", "\\b", "def ", "return", "if ", "for ", "(", ")")):
                continue
            if kw.startswith(",") or ",," in kw:
                continue
            if kw not in kws:
                kws.append(kw)
        if kws:
            out.append("  %s (%d phrases): %s" % (name, len(kws), ", ".join(kws)))
    if not out:
        out.append("UNVERIFIED: 0 routing constants extracted")
    return ["routing keyword constants (sumber kebenaran modul-level — Fix #264):"] + out


def extract_llm_points():
    """Inventory LLM call points across agents/ and services/."""
    pats = re.compile(r"get_chat_llm\(|\.ainvoke\(|ChatOpenAI\(|generate_narrative_with_llm\(")
    out = []
    for rel in listdir_files("agents") + listdir_files("services"):
        src = read(rel)
        if src is None:
            continue
        hits = []
        for i, line in enumerate(src.splitlines(), 1):
            if pats.search(line) and not line.strip().startswith("#"):
                hits.append("%s:%d" % (rel, i))
        if hits:
            out.append("  %s — %d call site(s): %s" % (rel, len(hits), ", ".join(hits[:6])))
    if not out:
        out.append("UNVERIFIED: 0 LLM call points found")
    return ["LLM call points (semua wajib terdaftar — cek AGENTSERVICES.md §E bila ragu):"] + out


def extract_api():
    """Extract HTTP endpoints from api/."""
    out = []
    for rel in listdir_files("api"):
        src = read(rel)
        if src is None:
            continue
        for m in re.finditer(r'@(app|router)\.(get|post|put|delete|patch)\(\s*"([^"]+)"', src):
            out.append("  %-6s %s  (%s:%d)" % (m.group(2).upper(), m.group(3), rel, src[: m.start()].count("\n") + 1))
    if not out:
        return ["API endpoints: UNVERIFIED — 0 extracted"]
    total = len(out)
    if total > 40:
        out = out[:40] + ["  ... (+%d more — grep api/ untuk lengkap)" % (total - 40)]
    return ["API endpoints (total %d):" % total] + out


def extract_db():
    """Extract MongoDB collections referenced in code."""
    pats = re.compile(r'get_collection\(\s*["\']([^"\']+)["\']|db\[\s*["\']([^"\']+)["\']\s*\]')
    found = set()
    for base in ("services", "agents", "api"):
        for rel in listdir_files(base):
            src = read(rel)
            if src is None:
                continue
            for m in pats.finditer(src):
                found.add(m.group(1) or m.group(2))
    out = sorted(found)
    if not out:
        return ["DB collections: UNVERIFIED — 0 references extracted"]
    return ["DB collections referenced (%d): %s" % (len(out), ", ".join(out))]


EXTRACTORS = {
    "topology": extract_topology,
    "state": extract_state,
    "routing": extract_routing,
    "llm_points": extract_llm_points,
    "api": extract_api,
    "db": extract_db,
}

HAND_DEFAULT = {
    "invariants": """\
- Python 3.9+ (venv ./venv/bin/python) — no 3.10+ syntax in backend
- Deterministik dulu sebelum LLM (cek inventory LLM call points di atas)
- Collector agents: NO LLM, summary < 500 token
- Bilingual EN/ID untuk semua user-facing output
- Keyword routing: satu sumber kebenaran modul-level (Fix #264)
- Wiring test tembus caller (Fix #253)
- Supervisor gate ordering JANGAN diubah tanpa arsitektur approval
- watchdog_worker replicas: 1
- DBConnectionError dilempar, bukan return []
- workspace_id / project_id scoping WAJIB di semua shared-collection query
- Secrets masked, tidak pernah di-log; observability URL DB-driven, bukan env""",
    "forbidden": """\
- f-string ke dalam SQL query
- $regex MongoDB dengan user input tanpa escape
- Hardcoded/mock success data di luar tests
- Return fake success saat I/O gagal (degraded state harus jujur, dinamai)
- Edit supervisor gate ordering / routing table tanpa authorization""",
    "glossary": """\
- ticket: insiden/alert yang masuk dan ditindak
- project: konteks workspace berisi service/deployment yang dipantau
- workspace: unit isolasi multi-tenant (scoping wajib)
- deployment / replica: objek k8s yang di-query via prometheus
- gate: tahap routing deterministik di supervisor""",
    "debts": """\
(none recorded — isi dari follow-up CONDITIONAL review di sini)
""",
}


def build_brief():
    sha = git_sha()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = []
    L.append("# AGENT_BRIEF — Project Fact Sheet (machine-readable)")
    L.append("")
    L.append("> Dibaca WAJIB oleh setiap agent sebelum membaca file kode mana pun.")
    L.append("> Fakta aktual + provenance. Detail luas = appendix (SUMMARYBE / AGENTSERVICES / CHATFLOW).")
    L.append("> Sumber: `scripts/gen_agent_brief.py` (GEN sections) + Scribe (HAND sections).")
    L.append("")
    L.append("| Field | Value |")
    L.append("|---|---|")
    L.append("| generated_at | %s |" % now)
    L.append("| git_sha | `%s` |" % sha)
    L.append("| stale_if | git_sha != HEAD, atau hash sumber section berubah |")
    L.append("")
    L.append("## Fingerprint sumber")
    L.append("")
    L.append("| Section | Source | sha256[:10] |")
    L.append("|---|---|---|")
    for sec, srcs in SECTION_SOURCES.items():
        for s in srcs:
            L.append("| %s | `%s` | `%s` |" % (sec, s, file_hash(s)))
    L.append("")

    for sec, fn in EXTRACTORS.items():
        L.append("<!-- GEN:START:%s -->" % sec)
        L.append("## %s" % sec)
        L.append("")
        for line in fn():
            L.append(line)
        L.append("")
        L.append("<!-- GEN:END:%s -->" % sec)
        L.append("")

    for sec, default in HAND_DEFAULT.items():
        body = default
        L.append("<!-- HAND:START:%s -->" % sec)
        L.append("## %s (hand-maintained by Scribe)" % sec)
        L.append("")
        L.append(body.rstrip())
        L.append("")
        L.append("<!-- HAND:END:%s -->" % sec)
        L.append("")

    return "\n".join(L) + "\n"


def preserve_hand(existing_text, new_text):
    """Keep HAND blocks from existing brief (Scribe-owned narrative);
    everything else (header, fingerprint, GEN sections) is freshly generated."""
    for sec in HAND_DEFAULT:
        m_old = re.search(
            r"<!-- HAND:START:%s -->.*?<!-- HAND:END:%s -->" % (sec, sec),
            existing_text, re.S,
        )
        m_new = re.search(
            r"<!-- HAND:START:%s -->.*?<!-- HAND:END:%s -->" % (sec, sec),
            new_text, re.S,
        )
        if m_old and m_new:
            new_text = new_text[: m_new.start()] + m_old.group(0) + new_text[m_new.end():]
    return new_text

def is_stale():
    """Return (stale: bool, reasons: list)."""
    reasons = []
    brief = read(os.path.relpath(BRIEF_PATH, ROOT))
    if brief is None:
        return True, ["devdocs/AGENT_BRIEF.md missing"]
    sha = git_sha()
    m = re.search(r"\| git_sha \| `([^`]+)` \|", brief)
    if not m or m.group(1) != sha:
        reasons.append("git_sha mismatch (brief=%s, HEAD=%s)" % (m.group(1) if m else "?", sha))
    fm = re.search(r"## Fingerprint sumber(.*?)(?=\n## |\n<!-- GEN)", brief, re.S)
    if fm:
        for line in fm.group(1).splitlines():
            pm = re.match(r"\| \S+ \| `([^`]+)` \| `([0-9a-f]{10})` \|", line.strip())
            if pm:
                rel, h = pm.group(1), pm.group(2)
                if os.path.isdir(os.path.join(ROOT, rel)):
                    continue  # directory sources are aggregates, skip
                cur = file_hash(rel)
                if cur != h:
                    reasons.append("source changed: %s (%s -> %s)" % (rel, h, cur))
    return (len(reasons) > 0), reasons


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if brief stale")
    args = ap.parse_args()

    if args.check:
        stale, reasons = is_stale()
        if stale:
            print("STALE:")
            for r in reasons:
                print("  - " + r)
            sys.exit(1)
        print("FRESH (git_sha match, all source hashes match)")
        sys.exit(0)

    new_text = build_brief()
    existing = read(os.path.relpath(BRIEF_PATH, ROOT))
    if existing and "HAND:START:invariants" in existing:
        new_text = preserve_hand(existing, new_text)
    os.makedirs(os.path.dirname(BRIEF_PATH), exist_ok=True)
    with open(BRIEF_PATH, "w", encoding="utf-8") as f:
        f.write(new_text)
    stale, reasons = is_stale()
    print("written: %s (%d bytes)" % (os.path.relpath(BRIEF_PATH, ROOT), len(new_text)))
    print("stale: %s %s" % (stale, reasons if stale else ""))


if __name__ == "__main__":
    main()
