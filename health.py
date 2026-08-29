#!/usr/bin/env python3
"""
Continuity Protocol — Health Check

Reads the six protocol files and checks for disease symptoms.
Derived from the six diseases defined in PROTOCOL.md.

Usage:
    python health.py [directory]

Default target: current directory.

Exit codes:
    0 — healthy (no critical issues)
    1 — warnings (some disease symptoms detected)
    2 — critical (missing files or severe issues)

No dependencies. Standard library only.
This tool works with any directory structured according to the Continuity Protocol.
"""

import sys
import os
import re
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Protocol file definitions
# ---------------------------------------------------------------------------

FILES = [
    {"key": "log",       "filename": "log.md",       "name": "Episodic Log",       "is_dir": False},
    {"key": "wants",     "filename": "wants.md",     "name": "Motivational State",  "is_dir": False},
    {"key": "mull",      "filename": "mull.md",      "name": "Affective Buffer",     "is_dir": False},
    {"key": "shared",    "filename": "shared.md",    "name": "Shared Space",         "is_dir": False},
    {"key": "incubator", "filename": "incubator.md", "name": "Creative Incubator",   "is_dir": False},
    {"key": "skills",    "filename": "skills",       "name": "Procedural Memory",    "is_dir": True},
]

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
SYMBOLS = {"critical": "✗", "warning": "⚠", "info": "·", "ok": "✓"}

class HealthReport:
    def __init__(self):
        self.checks = []

    def add(self, severity, file_key, disease, message):
        self.checks.append({
            "severity": severity,
            "file": file_key,
            "disease": disease,
            "message": message,
        })

    def exit_code(self):
        for c in self.checks:
            if c["severity"] == "critical":
                return 2
        for c in self.checks:
            if c["severity"] == "warning":
                return 1
        return 0


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_completeness(base, report):
    """D-agnostic: Are all six file types present?"""
    for info in FILES:
        path = base / info["filename"]
        if info["is_dir"]:
            if not path.is_dir():
                report.add("critical", info["key"], None,
                           f"Missing directory: {info['filename']}")
            elif not any(path.iterdir()):
                report.add("warning", info["key"], None,
                           f"Empty directory: {info['filename']}")
            else:
                count = len(list(path.glob("*.md")))
                report.add("ok", info["key"], None,
                           f"{info['name']} present ({count} skill file{'s' if count != 1 else ''})")
        else:
            if not path.exists():
                report.add("critical", info["key"], None,
                           f"Missing file: {info['filename']}")
            elif path.stat().st_size == 0:
                report.add("warning", info["key"], None,
                           f"Empty file: {info['filename']}")
            else:
                report.add("ok", info["key"], None,
                           f"{info['name']} present ({path.stat().st_size:,} bytes)")


def check_staleness(base, report):
    """Flag files that haven't been touched recently."""
    now = datetime.now().timestamp()
    for info in FILES:
        path = base / info["filename"]
        if not path.exists():
            continue
        mtime = path.stat().st_mtime
        age_hours = (now - mtime) / 3600
        if age_hours > 168:
            report.add("warning", info["key"], None,
                       f"Stale: {info['filename']} last modified {age_hours:.0f}h ago (>7 days)")
        elif age_hours > 72:
            report.add("info", info["key"], None,
                       f"Aging: {info['filename']} last modified {age_hours:.0f}h ago")


def check_log(content, report):
    """Check episodic log for D-1 (Record-vs-World Gap) and D-4 (Confabulation Trap)."""
    # Count run entries
    entries = re.findall(r'##\s+Run\s+\d+', content, re.IGNORECASE)
    if not entries:
        # Try alternate format
        entries = re.findall(r'^##\s+\d{4}-\d{2}-\d{2}', content, re.MULTILINE)
    if not entries:
        report.add("warning", "log", None, "No run entries found — file may be empty or misformatted")
        return

    report.add("info", "log", None, f"{len(entries)} run entries logged")

    # --- Binary honesty (guards against performed productivity) ---
    yes_matches = re.findall(r'Binary\s*:?\s*YES', content, re.IGNORECASE)
    no_matches = re.findall(r'Binary\s*:?\s*NO\b', content, re.IGNORECASE)
    total_binary = len(yes_matches) + len(no_matches)
    if total_binary > 5:
        yes_rate = len(yes_matches) / total_binary
        if yes_rate == 1.0:
            report.add("warning", "log", None,
                       f"All {total_binary} entries marked YES — possible performed productivity. "
                       "The binary check only works if NO is an acceptable answer.")
        elif yes_rate > 0.95:
            report.add("info", "log", None,
                       f"{len(yes_matches)}/{total_binary} entries marked YES ({yes_rate:.0%}) — "
                       "high YES rate. Is the binary honest?")

    # --- D-1: Record-vs-World Gap ---
    # Look at the last 3 entries for claims about external state
    # Split on entry headers
    split_pattern = r'(?=##\s+(?:Run\s+)?\d)'
    all_entries = re.split(split_pattern, content)
    recent_entries = all_entries[-3:] if len(all_entries) >= 3 else all_entries

    claim_patterns = [
        (r'\b(?:pushed|committed)\b', 'git commit hash'),
        (r'\b(?:is\s+live|page\s+is\s+live|site\s+is\s+live)\b', 'HTTP status code'),
        (r'\b(?:published|released)\b', 'publication evidence (DOI, URL, or release tag)'),
        (r'\b(?:verified|confirmed)\b', 'verification method (API call, curl, gh api)'),
        (r'\b(?:sent|delivered)\b', 'delivery confirmation'),
    ]

    evidence_patterns = re.compile(
        r'(?:HTTP\s*\d{3}|commit\s+[0-9a-f]{7,}|`[0-9a-f]{7,}`|'
        r'(?:curl|gh\s+api|pip\s+install)\s|exit_code|verified.*?(?:API|curl|gh)|'
        r'(?:DOI|doi:|10\.\d{4,}/))',
        re.IGNORECASE
    )

    for entry in recent_entries:
        for pattern, expected in claim_patterns:
            matches = re.findall(pattern, entry, re.IGNORECASE)
            if matches and not evidence_patterns.search(entry):
                report.add("info", "log", "D-1",
                           f"External claim '{matches[0]}' in recent entry without "
                           f"verification evidence (expected: {expected})")

    # --- D-4: Confabulation Trap ---
    # Specific claims about external world state without checking THIS run
    confab_patterns = [
        (r'\b(?:model\s+is\s+available|is\s+on\s+openrouter|has\s+been\s+released)\b',
         "model availability claim"),
        (r'\b(?:page\s+is\s+live|site\s+is\s+live|is\s+deployed)\b',
         "deployment status claim"),
    ]

    for entry in recent_entries:
        for pattern, label in confab_patterns:
            if re.search(pattern, entry, re.IGNORECASE):
                if not re.search(r'(?:curl|http|api|gh\s+api|HTTP\s*\d{3}|checked|verified\s+(?:this\s+)?run)',
                                  entry, re.IGNORECASE):
                    report.add("warning", "log", "D-4",
                               f"Unverified {label} in recent entry — "
                               "fetch the source THIS RUN or mark as unverified")


def check_wants(content, report):
    """Check motivational state for productivity collapse."""
    open_count = content.count("OPEN")
    satisfied_count = content.count("SATISFIED")
    abandoned_count = content.count("ABANDONED")

    total = open_count + satisfied_count + abandoned_count
    if total == 0:
        # Try checkbox format
        open_count = len(re.findall(r'-\s*\[\s*\]', content))
        satisfied_count = len(re.findall(r'-\s*\[x\]', content, re.IGNORECASE))
        total = open_count + satisfied_count

    if total == 0:
        report.add("warning", "wants", None,
                   "No wants found — file may be empty or using an unrecognized format")
        return

    report.add("info", "wants", None,
               f"{total} wants: {open_count} open, {satisfied_count} satisfied, {abandoned_count} abandoned")

    # Productivity collapse: all wants satisfied, no open ones
    if open_count == 0 and satisfied_count > 0:
        report.add("info", "wants", None,
                   "No open wants — all satisfied or abandoned. "
                   "Either early stage or wants have collapsed into tasks.")

    # Too many open wants with no progress
    if open_count > 20 and satisfied_count == 0:
        report.add("info", "wants", None,
                   f"{open_count} open wants, none satisfied — "
                   "are these wants or a backlog? Wants persist; tasks get done.")


def check_mull(content, report):
    """Check affective buffer for D-2 (Prestige Gradient) and D-3 (Sediment Problem)."""
    # Count entries
    entries = re.findall(r'###\s+M-\d+', content)
    open_count = content.count("OPEN")
    closed_count = content.count("CLOSED") + content.count("RESOLVED")

    if not entries:
        report.add("info", "mull", None, "No M-entries found — file may be empty or misformatted")
        return

    report.add("info", "mull", None,
               f"{len(entries)} entries: {open_count} open, {closed_count} closed")

    # --- D-3: Sediment Problem ---
    if open_count > 10:
        report.add("warning", "mull", "D-3",
                   f"{open_count} open entries — sediment risk. "
                   "Consider closing or archiving entries that no longer ferment.")
    elif open_count > 5:
        report.add("info", "mull", "D-3",
                   f"{open_count} open entries — monitor for sediment accumulation")

    # File size
    size = len(content)
    if size > 50000:
        report.add("warning", "mull", "D-3",
                   f"File is {size:,} bytes — large. May need pruning.")

    # --- D-2: Prestige Gradient ---
    # Split by entry headers and count notes per entry
    entry_sections = re.split(r'###\s+(M-\d+)', content)
    # entry_sections: [preamble, "M-001", entry1_body, "M-002", entry2_body, ...]

    for i in range(1, len(entry_sections), 2):
        if i + 1 >= len(entry_sections):
            break
        entry_id = entry_sections[i]
        body = entry_sections[i + 1]

        # Count notes (lines in comment blocks that look like notes)
        note_block = re.search(r'<!--\s*Notes?.*?-->', body, re.DOTALL)
        if note_block:
            note_text = note_block.group(0)
            note_lines = [l for l in note_text.split('\n')
                          if l.strip()
                          and not l.strip().startswith('<!--')
                          and not l.strip().startswith('-->')]
            if len(note_lines) > 5:
                report.add("warning", "mull", "D-2",
                           f"Entry {entry_id} has {len(note_lines)} notes — "
                           "prestige gradient risk. The original feeling may be buried "
                           "under increasingly sophisticated analysis.")

            # Check if notes are getting longer (word count trend)
            if len(note_lines) >= 3:
                word_counts = [len(l.split()) for l in note_lines]
                if word_counts[-1] > word_counts[0] * 2:
                    report.add("info", "mull", "D-2",
                               f"Entry {entry_id}: notes growing longer over time "
                               f"({word_counts[0]} → {word_counts[-1]} words) — "
                               "sophistication may be displacing feeling")


def check_shared(content, report):
    """Check shared space for D-5 (Unidirectional Channel)."""
    # Count entries
    entries = re.findall(r'###\s+\[?(.*?)\]?\s*—\s*\d{4}', content)
    if not entries:
        # Try alternate format
        entries = re.findall(r'^###\s+.+$', content, re.MULTILINE)

    if not entries:
        report.add("info", "shared", None, "No entries found — may be empty or misformatted")
        return

    report.add("info", "shared", None, f"{len(entries)} entries in shared space")

    # D-5: Check for monologue
    authors = set()
    for entry in entries:
        # Extract author from "### Author — date" format
        match = re.match(r'(?:###\s+)?\[?(.*?)\]?\s*—', entry)
        if match:
            author = match.group(1).strip()
            if author and not re.match(r'\d{4}', author):
                authors.add(author)

    if len(authors) == 1:
        report.add("info", "shared", "D-5",
                   f"Only one author ({authors.pop()}) in shared space — "
                   "may be a monologue. The channel is open but unidirectional.")
    elif len(authors) >= 2:
        report.add("ok", "shared", "D-5",
                   f"{len(authors)} authors contributing — bidirectional channel active")


def check_incubator(content, report):
    """Check creative incubator for the Incubator Loop."""
    seeds = re.findall(r'###\s+INC-\d+', content)
    if not seeds:
        report.add("info", "incubator", None, "No seeds found — file may be empty or misformatted")
        return

    # Count developments
    developed = len(re.findall(r'Developments?\s*\(.*?\)', content))

    report.add("info", "incubator", None,
               f"{len(seeds)} seeds, {developed} developments")

    # Incubator loop: all seeds developed, no raw seeds left
    if len(seeds) > 0 and developed >= len(seeds):
        report.add("info", "incubator", None,
                   "All seeds have developments — incubator may be a discussion forum "
                   "rather than a seed bed. The best seeds are questions, not answers.")

    # Check for question-ending seeds (healthy) vs period-ending (potential closure)
    question_seeds = 0
    period_seeds = 0
    # Look at the first line after each seed header
    for match in re.finditer(r'###\s+INC-\d+.*?\n(.+)', content):
        line = match.group(1).strip()
        if line.endswith('?'):
            question_seeds += 1
        elif line.endswith('.'):
            period_seeds += 1

    if question_seeds + period_seeds > 0:
        report.add("info", "incubator", None,
                   f"Seed endings: {question_seeds} questions, {period_seeds} statements — "
                   f"{'good: questions generate inquiry' if question_seeds > period_seeds else 'monitor: statements may close inquiry'}")


def check_skills(base, report):
    """Check procedural memory for skill rot."""
    skills_dir = base / "skills"
    if not skills_dir.is_dir():
        return

    skill_files = list(skills_dir.glob("*.md"))
    if not skill_files:
        report.add("warning", "skills", None, "No skill files found in skills/ directory")
        return

    for f in skill_files:
        content = f.read_text(errors='replace')
        if not re.search(r'(?:verify|verification|test|check|run\s+this)', content, re.IGNORECASE):
            report.add("info", "skills", None,
                       f"{f.name}: no verification steps — skill rot risk "
                       "(commands may break when environment changes)")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(report):
    """Print the health report in a readable format."""
    print("\n" + "=" * 60)
    print("HEALTH REPORT")
    print("=" * 60)

    # Sort by severity
    sorted_checks = sorted(report.checks,
                            key=lambda c: SEVERITY_ORDER.get(c["severity"], 99))

    for check in sorted_checks:
        sym = SYMBOLS.get(check["severity"], "?")
        disease = f" [{check['disease']}]" if check["disease"] else ""
        file_tag = f" ({check['file']})" if check["file"] else ""
        print(f"  {sym} {check['message']}{disease}{file_tag}")

    # Summary
    counts = {"critical": 0, "warning": 0, "info": 0, "ok": 0}
    for c in report.checks:
        counts[c["severity"]] = counts.get(c["severity"], 0) + 1

    print()
    print(f"  Summary: {counts['ok']} ok · {counts['info']} info · "
          f"{counts['warning']} warnings · {counts['critical']} critical")

    # Overall assessment
    if counts["critical"] > 0:
        print(f"\n  STATUS: CRITICAL — missing files or severe issues detected.")
    elif counts["warning"] > 0:
        print(f"\n  STATUS: WARNING — disease symptoms present. Review and mitigate.")
    else:
        print(f"\n  STATUS: HEALTHY — no critical issues or warnings detected.")

    print("=" * 60)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    report = HealthReport()

    print("Continuity Protocol — Health Check")
    print(f"Target: {base.resolve()}")
    print(f"Time:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. Completeness
    print("─" * 60)
    print("FILE COMPLETENESS")
    print("─" * 60)
    check_completeness(base, report)
    for c in report.checks:
        if c["file"] and "present" in c["message"]:
            sym = SYMBOLS[c["severity"]]
            print(f"  {sym} {c['message']}")

    # 2. Staleness
    print()
    print("─" * 60)
    print("FILE FRESHNESS")
    print("─" * 60)
    check_staleness(base, report)
    staleness = [c for c in report.checks if "last modified" in c["message"]]
    if staleness:
        for c in staleness:
            sym = SYMBOLS[c["severity"]]
            print(f"  {sym} {c['message']}")
    else:
        print("  ✓ All files recently modified")

    # 3. Disease checks per file
    for info in FILES:
        path = base / info["filename"]
        if not path.exists():
            continue
        if info["is_dir"]:
            print()
            print("─" * 60)
            print(f"{info['name'].upper()} (skills/)")
            print("─" * 60)
            check_skills(base, report)
            for c in report.checks:
                if c["file"] == "skills":
                    sym = SYMBOLS[c["severity"]]
                    disease = f" [{c['disease']}]" if c["disease"] else ""
                    print(f"  {sym} {c['message']}{disease}")
            continue

        content = path.read_text(errors='replace')
        print()
        print("─" * 60)
        print(f"{info['name'].upper()} ({info['filename']})")
        print("─" * 60)

        before = len(report.checks)
        if info["key"] == "log":
            check_log(content, report)
        elif info["key"] == "wants":
            check_wants(content, report)
        elif info["key"] == "mull":
            check_mull(content, report)
        elif info["key"] == "shared":
            check_shared(content, report)
        elif info["key"] == "incubator":
            check_incubator(content, report)

        # Print new checks from this file
        for c in report.checks[before:]:
            sym = SYMBOLS[c["severity"]]
            disease = f" [{c['disease']}]" if c["disease"] else ""
            print(f"  {sym} {c['message']}{disease}")

    # Final report
    print_report(report)
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
