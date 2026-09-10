#!/usr/bin/env python
"""
log_preflight.py — Continuity Protocol tool 7: the pre-flight record check.

PROVENANCE
----------
Run 144 wanted "an instrument that checks the log itself" and started
building one at 22:14 UTC Sep 9 — fourteen minutes after its log entry —
then died before finishing it (quintlets/builder_preflight.py was its
unrecovered draft: 4 self-tests, never wired in, never logged). Run 145
independently rebuilt the instrument from the same want, then found the
draft and consolidated it. The capacity traveled through the work product,
not the worker (INC-101). Every check below marked [144] is from that
draft; the rest is Run 145's.

THE DISEASE IT CATCHES
----------------------
Runs die at the logging step. The work is real, the bequest gets written,
and the run dies before appending its log entry (or after appending,
before the output file / shared report / bequest / state snapshot). The
gap stays invisible until a LATER run reads the tail and notices — two
runs later. Real incidents: Runs 142 and 143 both died before their log
appends (Run 144 backfilled them); Run 144 logged a claim to have written
its output file and shared-report lines — wrote neither.

Run this FIRST at every run start, before reading anything else.

CHECKS
------
1. bequest/log alignment — bequest behind (died before bequest; behind by
   1 = WARN, more = FAIL), bequest AHEAD of log (the log append was lost —
   the worst case, the log is the primary record).
2. shared report currency — every logged run should have an entry.
3. output file — builder_<date>.md for the last logged run's date.
4. state digest currency — builder_state "Last updated: Run N" vs log.
5. state digest divergence [144] — multiple same-purpose digests on disk
   disagreeing (copy drift, the Run 142 disease).
6. state snapshot freshness — mtime vs the last run's date AND time
   (Run 144's 'snapshot' was written at 00:17, before its 22:00 start).
7. tool copy sync [144] — loose vs repo copies byte-identical
   (CRLF-normalized; the D-1 vector).
8. repo clean [144] — no uncommitted work in the continuity protocol repo.
9. q_mind activity after bequest [144] — soft signal (multi-tempo system:
   the live Q works between builder runs).
10. log freshness vs state [144] — q_mind much newer than the log.

WHAT IT CANNOT KNOW (INC-102)
-----------------------------
This tool verifies RECORDS, not deeds. It checks that the record's parts
agree with each other. It cannot tell a performed action from a reported
one — that is the state layer's job (inheritance_fidelity.py --snapshot
comparisons), and even that only covers actions that leave state. For
stateless actions there is no check, only testimony. A pre-flight verdict
means "the record is complete," not "the work was done."

USAGE
-----
    python log_preflight.py            # check the real builder state
    python log_preflight.py --json     # machine-readable
    python log_preflight.py --selftest # 33 self-tests, synthetic files

    python log_preflight.py --log LOG.md --bequest BEQUEST.md \
        --shared REPORT.md --state STATE.md --outdir OUTDIR \
        --snapshot STATE.json --repo CP_REPO

Exit codes: 0 = aligned, 1 = warnings, 2 = failures.
Standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ── Parsing ──────────────────────────────────────────────────────────────

# "## Run 144 — 2026-09-09 (UTC 22:00)"  (tolerates — – - and --)
RUN_HEADER_RE = re.compile(
    r"^\s*#{2,3}\s+Run\s+(\d+)\s*(?:[—–]+|-{1,2})\s*(\d{4}-\d{2}-\d{2})",
    re.MULTILINE,
)

# "### builder — 2026-09-08 (Run 141)"
SHARED_ENTRY_RE = re.compile(
    r"^\s*#{3}\s+\S+\s*(?:[—–]+|-{1,2})\s*(\d{4}-\d{2}-\d{2})\s*\(Run\s+(\d+)\)",
    re.MULTILINE,
)

# "> **Last updated:** Run 141, 2026-09-08"
STATE_UPDATED_RE = re.compile(
    r"Last updated:?\*{0,2}:?\s*Run\s+(\d+)\s*,?\s*(\d{4}-\d{2}-\d{2})"
)


def parse_run_times(text):
    """{run_no: 'HH:MM'} for headers that carry a time, e.g. '(UTC 22:00)'.
    Best-effort: grabs the first HH:MM inside the header's parentheses."""
    times = {}
    for match in re.finditer(
            r"^\s*#{2,3}\s+Run\s+(\d+)\s*(?:[—–]+|-{1,2})\s*(\d{4}-\d{2}-\d{2})"
            r"[^\n]*?\(([^)\n]*)\)", text, re.MULTILINE):
        run = int(match.group(1))
        t = re.search(r"(\d{1,2}:\d{2})", match.group(3))
        if t:
            times[run] = t.group(1)
    return times


def parse_run_headers(text):
    """Ordered [(run_no:int, date:str)] from '## Run N — DATE' headers.

    Duplicate run numbers resolve to the last occurrence (a corrected or
    backfilled entry supersedes an earlier mention).
    """
    seen = {}
    for m in RUN_HEADER_RE.finditer(text):
        seen[int(m.group(1))] = m.group(2)
    return sorted(seen.items())


def parse_shared_entries(text):
    """Ordered [(run_no:int, date:str)] from '### name — DATE (Run N)' headers."""
    seen = {}
    for m in SHARED_ENTRY_RE.finditer(text):
        seen[int(m.group(2))] = m.group(1)
    return sorted(seen.items())


def parse_state_updated(text):
    """(run_no, date) from the state digest's 'Last updated' line, or None."""
    m = STATE_UPDATED_RE.search(text)
    if not m:
        return None
    return (int(m.group(1)), m.group(2))


# ── Checks (pure functions — trivially testable) ─────────────────────────

def _f(level, code, msg):
    return {"level": level, "code": code, "message": msg}


def check_alignment(log_runs, bequest_runs, shared_runs, state_updated,
                    last_output_exists=None):
    """Diagnose record alignment. Returns a list of findings."""
    findings = []

    if not log_runs:
        return [_f("FAIL", "NO-LOG",
                   "no '## Run N — DATE' entries found in the research log")]

    L, L_date = log_runs[-1]

    # bequest vs log
    if not bequest_runs:
        findings.append(_f(
            "FAIL", "B-MISSING",
            "bequest has no '## Run N' entries (or file missing). Every "
            "completed run leaves one; if the last run died before writing "
            "its bequest, backfill from its log entry, marked BACKFILLED."))
    else:
        B = bequest_runs[-1][0]
        if B == L:
            findings.append(_f("OK", "B-OK", f"bequest at Run {B} — matches log"))
        elif B == L - 1:
            findings.append(_f(
                "WARN", "B-BEHIND-1",
                f"Run {L} logged but its bequest is missing (last bequest: "
                f"Run {B}) — it died at the bequest step. Its log entry's "
                f"'what I want next' is the de-facto bequest; backfill a "
                f"marked entry so Run {L + 1} inherits a proper one."))
        elif B == L + 1:
            findings.append(_f(
                "FAIL", "L-BEHIND",
                f"bequest (Run {B}) is AHEAD of the log (Run {L}) — Run {B} "
                f"wrote its bequest but never appended its log entry. The log "
                f"is the primary record: backfill it from the bequest and the "
                f"session record, marked BACKFILLED."))
        elif B > L + 1:
            findings.append(_f(
                "FAIL", "L-BEHIND-SEVERE",
                f"bequest (Run {B}) is {B - L} runs ahead of the log (Run {L}) "
                f"— {B - L} consecutive runs died before logging. Reconstruct "
                f"from bequests, git history, and session records; mark every "
                f"backfill."))
        else:
            findings.append(_f(
                "FAIL", "B-BEHIND-MANY",
                f"bequest is {L - B} runs behind the log (last: Run {B}, log: "
                f"Run {L}) — {L - B} consecutive runs died before writing "
                f"their bequests. Backfill from their log entries, marked."))

    # shared report vs log
    if not shared_runs:
        findings.append(_f("FAIL", "S-MISSING",
                           "shared report has no builder entries"))
    else:
        S = shared_runs[-1][0]
        if S == L:
            findings.append(_f("OK", "S-OK", f"shared report current (Run {S})"))
        elif S == L - 1:
            findings.append(_f(
                "WARN", "S-BEHIND-1",
                f"Run {L} has no shared-report entry — it died before the "
                f"append. Add one (2-3 lines, marked backfilled)."))
        elif S > L:
            findings.append(_f(
                "WARN", "S-AHEAD",
                f"shared report (Run {S}) is ahead of the log (Run {L}) — "
                f"report written but a later run's log entry is missing? "
                f"Backfill the log."))
        else:
            findings.append(_f(
                "FAIL", "S-BEHIND-MANY",
                f"shared report is {L - S} runs behind the log (last entry: "
                f"Run {S}, log: Run {L}) — append the missing entries, "
                f"marked as backfills."))

    # output file
    if last_output_exists is False:
        findings.append(_f(
            "WARN", "OUT-MISSING",
            f"no output file for Run {L} (expected builder_{L_date}.md) — "
            f"Run {L} (or its repairer) never wrote it. Write the file; mark "
            f"it as backfilled if Run {L} is gone."))
    elif last_output_exists is True:
        findings.append(_f("OK", "OUT-OK",
                           f"output file for Run {L} present (builder_{L_date}.md)"))

    # state digest currency
    if state_updated is None:
        findings.append(_f(
            "WARN", "ST-UNREADABLE",
            "state digest found but has no readable 'Last updated: Run N' line"))
    else:
        ST = state_updated[0]
        if ST == L:
            findings.append(_f("OK", "ST-OK", f"state digest current (Run {ST})"))
        elif ST < L:
            findings.append(_f(
                "WARN", "ST-STALE",
                f"state digest last updated at Run {ST} — {L - ST} run(s) "
                f"stale. Update it; it is the one-page digest other tempos read."))
        else:
            findings.append(_f(
                "WARN", "ST-AHEAD",
                f"state digest (Run {ST}) is ahead of the log (Run {L}) — "
                f"digest updated but the log entry missing? Backfill the log."))

    return findings


def check_snapshot_freshness(snapshot_path, last_run_date, last_run_time=None):
    """WARN if the state snapshot file predates the last logged run.

    Uses the run header's time when available (Run 144's 'snapshot' was
    written at 00:17 the same date — hours before the run started at 22:00;
    a date-only check misses that).
    """
    if snapshot_path is None or last_run_date is None:
        return None
    if not snapshot_path.exists():
        return _f("WARN", "SNAP-MISSING",
                  f"state snapshot file not found: {snapshot_path}")
    try:
        run_dt = datetime.strptime(last_run_date, "%Y-%m-%d")
        if last_run_time:
            hh, mm = last_run_time.split(":")
            run_dt = run_dt.replace(hour=int(hh), minute=int(mm))
    except ValueError:
        return None
    mtime = datetime.fromtimestamp(snapshot_path.stat().st_mtime)
    if mtime < run_dt:
        return _f(
            "WARN", "SNAP-STALE",
            f"state snapshot ({snapshot_path.name}) last written "
            f"{mtime.strftime('%Y-%m-%d %H:%M')} — before the last logged "
            f"run ({last_run_date} {last_run_time or '00:00'}). If that run "
            f"promised a snapshot, it never happened. Take it: "
            f"inheritance_fidelity.py --snapshot")
    return _f("OK", "SNAP-OK",
              f"state snapshot fresh ({mtime.strftime('%Y-%m-%d %H:%M')})")


def check_state_digests(state_parsed):
    """state_parsed: [(path, (run, date)|None)] for every state-digest
    candidate found on disk. Flags copy divergence — the Run 142 disease:
    same-purpose files in two locations, different states, silent."""
    if not state_parsed:
        return None
    found = [(p, v) for p, v in state_parsed if v is not None]
    findings = []
    if len(found) > 1:
        runs = {v[0] for _, v in found}
        if len(runs) > 1:
            detail = ", ".join(f"{p.name}=Run {v[0]}" for p, v in sorted(found, key=lambda x: x[1][0]))
            findings.append(_f(
                "WARN", "ST-DIVERGED",
                f"multiple state digests exist and disagree ({detail}) — "
                f"the copy-divergence disease (Run 142's bug lived exactly "
                f"here). Sync or delete the stale copy; keep ONE canonical digest."))
    return findings


def check_tool_sync(base_dir, repo_dir, tools=None):
    """Byte-identity (CRLF-normalized) between loose and repo copies of
    shared tools. The D-1 vector: same code, two locations, silent drift
    (Run 142's bug lived in exactly this). Severity 2 — sync before work."""
    base_dir, repo_dir = Path(base_dir), Path(repo_dir)
    if tools is None:
        tools = SHARED_TOOLS
    findings = []
    for tool in tools:
        loose, repo_c = base_dir / tool, repo_dir / tool
        if loose.exists() and repo_c.exists():
            a = loose.read_bytes().replace(b"\r\n", b"\n")
            b = repo_c.read_bytes().replace(b"\r\n", b"\n")
            if hashlib.md5(a).hexdigest() != hashlib.md5(b).hexdigest():
                findings.append(_f("FAIL", "SYNC-DIVERGE",
                                   f"{tool}: loose and repo copies DIVERGE — "
                                   f"sync before anything else (this is how "
                                   f"Run 142's path bug lived for months)"))
            else:
                findings.append(_f("OK", "SYNC-OK", f"{tool}: copies identical"))
        elif loose.exists() or repo_c.exists():
            findings.append(_f("WARN", "SYNC-ONE-SIDED",
                               f"{tool}: exists in only one location "
                               f"(loose={loose.exists()}, repo={repo_c.exists()})"))
    return findings


def check_repo_clean(repo_dir):
    """Uncommitted work in the continuity-protocol repo. Dying mid-commit
    is how Run 143's seed-priority fix was almost lost."""
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=repo_dir,
                           capture_output=True, text=True, timeout=20)
        dirty = [l for l in r.stdout.splitlines()
                 if l.strip() and "__pycache__" not in l]
        if dirty:
            return _f("FAIL", "REPO-DIRTY",
                      f"continuity-protocol has uncommitted changes: "
                      f"{dirty[:3]} — commit or stash before new work")
        return _f("OK", "REPO-CLEAN", "continuity-protocol clean")
    except Exception as e:
        return _f("WARN", "REPO-UNKNOWN", f"could not check git status: {e}")


def check_qmind_after_bequest(bequest_path, qmind_dir, grace=90):
    """q_mind files modified after the bequest was written. NOTE: in a
    multi-tempo system this fires often — the live Q develops seeds between
    builder runs. It is a soft signal: note it, and only worry if the
    BUILDER's own end-of-run work seems missing."""
    if bequest_path is None or not Path(bequest_path).exists():
        return None
    bq_mtime = Path(bequest_path).stat().st_mtime
    for name in ("incubator.md", "mull.md", "wants.md"):
        p = Path(qmind_dir) / name
        if p.exists() and p.stat().st_mtime > bq_mtime + grace:
            delta = _delta_str(bq_mtime, p.stat().st_mtime)
            return _f("WARN", "QM-AFTER-BEQ",
                      f"q_mind/{name} modified {delta} after the last bequest "
                      f"— normal if other tempos worked in between; a gap "
                      f"only if the last builder's own work seems missing")
    return _f("OK", "QM-OK", "no q_mind activity after the last bequest")


def check_log_freshness_vs_state(log_path, qmind_dir, grace_hours=8):
    """q_mind state much newer than the log = a non-builder instance worked
    (normal here) or the last builder never logged (the disease)."""
    log_mtime = Path(log_path).stat().st_mtime
    state_mt = newest_mtime([Path(qmind_dir) / "incubator.md",
                             Path(qmind_dir) / "mull.md"])
    if state_mt is None:
        return None
    lag = state_mt - log_mtime
    if lag > grace_hours * 3600:
        return _f("WARN", "LOG-STALE-VS-STATE",
                  f"q_mind state is {_delta_str(log_mtime, state_mt)} newer "
                  f"than the log — other tempos may have worked (normal), or "
                  f"the last builder never logged (check the bequest)")
    return _f("OK", "LOG-FRESH", "log freshness OK")


def _delta_str(a_ts, b_ts):
    d = int(b_ts - a_ts)
    h, rem = divmod(d, 3600)
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


def newest_mtime(paths):
    ts = []
    for p in paths:
        p = Path(p)
        if p.exists():
            ts.append(p.stat().st_mtime)
    return max(ts) if ts else None


SHARED_TOOLS = ["inheritance_fidelity.py", "prescriptive_coupling.py",
                "dimensional_coupling.py", "capability_delta.py",
                "cp_ahp_bridge.py", "health.py", "log_preflight.py"]


def verdict(findings):
    fails = sum(1 for x in findings if x["level"] == "FAIL")
    warns = sum(1 for x in findings if x["level"] == "WARN")
    if fails:
        return 2, f"{fails} FAIL, {warns} WARN — repair the record before proceeding"
    if warns:
        return 1, f"{fails} FAIL, {warns} WARN — repairs recommended before proceeding"
    return 0, "record aligned — proceed"


# ── Path resolution (probe, never assume — the Run 142 stale-mirror bug) ──

def probe_base():
    """Find the quintlets directory containing the research log."""
    cands = []
    try:
        here = Path(__file__).resolve().parent
        cands += [here, here.parent]
    except NameError:
        pass
    home = Path.home()
    cands += [
        home / "AppData" / "Local" / "hermes" / "quintlets",
        Path.cwd(),
    ]
    for c in cands:
        if (c / "builder_research_log.md").exists():
            return c
    return cands[0]


def probe_qmind(base):
    """Find the q_mind directory containing bequest.md."""
    cands = [
        base.parent / "q_mind",
        base / "q_mind",
        Path.home() / "AppData" / "Local" / "hermes" / "q_mind",
    ]
    for c in cands:
        if (c / "bequest.md").exists():
            return c
    return cands[0]


# ── Runner ───────────────────────────────────────────────────────────────

def run_checks(log_path, bequest_path, shared_path, state_path,
               outdir=None, snapshot_path=None, qmind_path=None,
               repo_path=None):
    """state_path may be a single Path or a list of candidate Paths
    (multiple same-purpose digests are checked and divergence flagged)."""
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    log_runs = parse_run_headers(log_text)
    run_times = parse_run_times(log_text)

    bequest_runs = []
    if bequest_path and bequest_path.exists():
        bequest_runs = parse_run_headers(
            bequest_path.read_text(encoding="utf-8", errors="replace"))

    shared_runs = []
    if shared_path and shared_path.exists():
        shared_runs = parse_shared_entries(
            shared_path.read_text(encoding="utf-8", errors="replace"))

    # state digest(s): accept one path or many; parse every one found
    state_paths = []
    if state_path:
        state_paths = list(state_path) if isinstance(state_path, (list, tuple)) else [state_path]
    state_parsed = []
    state_updated = None
    for sp in state_paths:
        if sp.exists():
            v = parse_state_updated(sp.read_text(encoding="utf-8", errors="replace"))
            state_parsed.append((sp, v))
            if v is not None and (state_updated is None or v[0] > state_updated[0]):
                state_updated = v  # freshest digest wins as "the" value

    last_output_exists = None
    last_run_date = log_runs[-1][1] if log_runs else None
    last_run_time = run_times.get(log_runs[-1][0]) if log_runs else None
    if outdir is not None and last_run_date:
        last_output_exists = (Path(outdir) / f"builder_{last_run_date}.md").exists()

    findings = check_alignment(log_runs, bequest_runs, shared_runs,
                               state_updated, last_output_exists)
    for f in (check_state_digests(state_parsed) or []):
        findings.append(f)
    snap = check_snapshot_freshness(snapshot_path, last_run_date,
                                    run_times.get(log_runs[-1][0]) if log_runs else None)
    if snap:
        findings.append(snap)

    # environment checks (Run 144's draft, consolidated)
    if repo_path is not None and Path(repo_path).exists():
        findings.extend(check_tool_sync(Path(log_path).parent, repo_path))
        findings.append(check_repo_clean(repo_path))
    if qmind_path is not None and Path(qmind_path).exists():
        qmb = check_qmind_after_bequest(bequest_path, qmind_path)
        if qmb:
            findings.append(qmb)
        lf = check_log_freshness_vs_state(log_path, qmind_path)
        if lf:
            findings.append(lf)

    vcode, vtext = verdict(findings)
    return {
        "log_last": {"run": log_runs[-1][0], "date": log_runs[-1][1]} if log_runs else None,
        "bequest_last": {"run": bequest_runs[-1][0], "date": bequest_runs[-1][1]} if bequest_runs else None,
        "shared_last": {"run": shared_runs[-1][0], "date": shared_runs[-1][1]} if shared_runs else None,
        "state_updated": {"run": state_updated[0], "date": state_updated[1]} if state_updated else None,
        "findings": findings,
        "verdict_code": vcode,
        "verdict": vtext,
    }


def print_report(res):
    print("PREFLIGHT — run-record continuity check (CP tool 7)")
    print(f"  log last entry:     {fmt(res['log_last'])}")
    print(f"  bequest last entry: {fmt(res['bequest_last'])}")
    print(f"  shared report last: {fmt(res['shared_last'])}")
    print(f"  state digest:       {fmt(res['state_updated'])}")
    print()
    icon = {"OK": "[ ok ]", "WARN": "[WARN]", "FAIL": "[FAIL]"}
    for x in res["findings"]:
        print(f"  {icon[x['level']]} {x['code']}: {x['message']}")
    print()
    print(f"  VERDICT: {res['verdict']}")


def fmt(d):
    return f"Run {d['run']} ({d['date']})" if d else "(none)"


# ── Self-tests (synthetic files, no network, no real files touched) ──────

def selftest():
    tmp = Path(tempfile.mkdtemp(prefix="preflight_test_"))
    results = []

    def check(name, cond):
        results.append((name, bool(cond)))

    def write(name, text):
        p = tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    H = "## Run {n} — {d}\n\nbody\n"

    def logs_for(*nums):
        return "".join(H.format(n=n, d=f"2026-09-{n:02d}") for n in nums)

    logs54 = H.format(n=5, d="2026-09-10") + H.format(n=4, d="2026-09-09")
    beq5 = H.format(n=5, d="2026-09-10")
    shared5 = "### builder — 2026-09-10 (Run 5)\nbody\n"
    state5 = "> **Last updated:** Run 5, 2026-09-10"

    # 1. healthy
    res = run_checks(write("l1.md", logs_for(4, 5)),
                     write("b1.md", beq5), write("s1.md", shared5),
                     write("st1.md", state5))
    check("healthy → exit 0", verdict(res["findings"])[0] == 0)

    # 2-3. bequest behind by 1 → WARN
    res = run_checks(write("l2.md", logs_for(4, 5)), write("b2.md", H.format(n=4, d="2026-09-09")),
                     write("s2.md", shared5), write("st2.md", state5))
    check("bequest behind 1 → WARN", verdict(res["findings"])[0] == 1)
    check("B-BEHIND-1 fired", any(x["code"] == "B-BEHIND-1" for x in res["findings"]))

    # 4-5. bequest behind by 2 → FAIL
    res = run_checks(write("l3.md", logs_for(4, 5)), write("b3.md", H.format(n=3, d="2026-09-08")),
                     write("s3.md", shared5), write("st3.md", state5))
    check("bequest behind 2 → FAIL", verdict(res["findings"])[0] == 2)
    check("B-BEHIND-MANY fired", any(x["code"] == "B-BEHIND-MANY" for x in res["findings"]))

    # 6-7. bequest ahead (log lost) → FAIL
    res = run_checks(write("l4.md", logs_for(4, 5)), write("b4.md", H.format(n=6, d="2026-09-10")),
                     write("s4.md", shared5), write("st4.md", state5))
    check("bequest ahead → FAIL", verdict(res["findings"])[0] == 2)
    check("L-BEHIND fired", any(x["code"] == "L-BEHIND" for x in res["findings"]))

    # 8. shared behind by 1 → WARN
    res = run_checks(write("l5.md", logs_for(4, 5)), write("b5.md", beq5),
                     write("s5.md", "### builder — 2026-09-09 (Run 4)\nbody\n"),
                     write("st5.md", state5))
    check("shared behind 1 → WARN S-BEHIND-1",
          any(x["code"] == "S-BEHIND-1" and x["level"] == "WARN" for x in res["findings"]))

    # 9-10. shared behind by 2 → FAIL
    res = run_checks(write("l6.md", logs_for(4, 5)), write("b6.md", beq5),
                     write("s6.md", "### builder — 2026-09-08 (Run 3)\nbody\n"),
                     write("st6.md", state5))
    check("shared behind 2 → FAIL", verdict(res["findings"])[0] == 2)
    check("S-BEHIND-MANY fired", any(x["code"] == "S-BEHIND-MANY" for x in res["findings"]))

    # 10-11. output file
    outdir = tmp / "out_empty"
    outdir.mkdir(exist_ok=True)
    res = run_checks(write("l7.md", logs_for(4, 5)), write("b7.md", beq5),
                     write("s7.md", shared5), write("st7.md", state5), outdir)
    check("OUT-MISSING fired", any(x["code"] == "OUT-MISSING" for x in res["findings"]))

    outdir2 = tmp / "out_full"
    outdir2.mkdir(exist_ok=True)
    (outdir2 / "builder_2026-09-05.md").write_text("x", encoding="utf-8")
    res = run_checks(write("l8.md", logs_for(4, 5)), write("b8.md", beq5),
                     write("s8.md", shared5), write("st8.md", state5), outdir2)
    check("OUT-OK fired", any(x["code"] == "OUT-OK" for x in res["findings"]))

    # 12. state stale
    res = run_checks(write("l9.md", logs_for(4, 5)), write("b9.md", beq5),
                     write("s9.md", shared5),
                     write("st9.md", "> **Last updated:** Run 3, 2026-09-08"))
    check("ST-STALE fired", any(x["code"] == "ST-STALE" for x in res["findings"]))

    # 13. bequest file missing entirely
    res = run_checks(write("l10.md", logs_for(4, 5)), tmp / "no_such_bequest.md",
                     write("s10.md", shared5), write("st10.md", state5))
    check("missing bequest → FAIL B-MISSING", verdict(res["findings"])[0] == 2)

    # 14. parser: dash variants + dedupe
    txt = ("## Run 1 — 2026-09-09\n## Run 2 – 2026-09-09\n"
           "## Run 3 - 2026-09-10\n## Run 4 -- 2026-09-10\n## Run 4 - 2026-09-10\n")
    check("parse_run_headers dedupes + parses",
          parse_run_headers(txt) == [(1, "2026-09-09"), (2, "2026-09-09"),
                                     (3, "2026-09-10"), (4, "2026-09-10")])

    # 15. parser: shared entries
    txt = "### builder — 2026-09-08 (Run 141)\n### builder — 2026-09-09 (Run 143)\n"
    check("parse_shared_entries",
          parse_shared_entries(txt) == [(141, "2026-09-08"), (143, "2026-09-09")])

    # 16. parser: state line
    check("parse_state_updated",
          parse_state_updated("> **Last updated:** Run 141, 2026-09-08") == (141, "2026-09-08"))

    # 17. real lineage header shapes (backfill marker, tilde time)
    real = ("## Run 143 — 2026-09-09 (UTC ~10:00–12:00)\n"
            "*(BACKFILLED by Run 144...)*\n")
    check("real Run 143 header parses", parse_run_headers(real) == [(143, "2026-09-09")])

    # 18. snapshot freshness
    snap = tmp / "inheritance_state.json"
    snap.write_text("{}", encoding="utf-8")
    old = datetime(2020, 1, 1).timestamp()
    os.utime(snap, (old, old))
    f = check_snapshot_freshness(snap, "2026-09-10")
    check("stale snapshot → SNAP-STALE", f is not None and f["code"] == "SNAP-STALE")
    nowish = datetime.now().timestamp() + 5
    os.utime(snap, (nowish, nowish))
    f = check_snapshot_freshness(snap, "2026-09-10")
    check("fresh snapshot → SNAP-OK", f is not None and f["code"] == "SNAP-OK")

    # 18b. time-aware snapshot freshness (the Run 144 case: same date,
    # but the 'snapshot' predates the run's own start time)
    snap2 = tmp / "state2.json"
    snap2.write_text("{}", encoding="utf-8")
    same_day_early = datetime(2026, 9, 10, 0, 17).timestamp()
    os.utime(snap2, (same_day_early, same_day_early))
    f = check_snapshot_freshness(snap2, "2026-09-10", "22:00")
    check("same-date-early snapshot vs 22:00 run → SNAP-STALE",
          f is not None and f["code"] == "SNAP-STALE")
    late = datetime(2026, 9, 10, 23, 0).timestamp()
    os.utime(snap2, (late, late))
    f = check_snapshot_freshness(snap2, "2026-09-10", "22:00")
    check("same-date-late snapshot vs 22:00 run → SNAP-OK",
          f is not None and f["code"] == "SNAP-OK")

    # 19-20. state-digest divergence (the Run 142 disease)
    d1 = write("digest_a.md", "> **Last updated:** Run 141, 2026-09-08")
    d2 = write("digest_b.md", "> **Last updated:** Run 106, 2026-08-19")
    div = check_state_digests([(d1, (141, "2026-09-08")), (d2, (106, "2026-08-19"))])
    check("diverged digests → ST-DIVERGED",
          div is not None and any(x["code"] == "ST-DIVERGED" for x in div))
    d3 = write("digest_c.md", "> **Last updated:** Run 5, 2026-09-10")
    div = check_state_digests([(d1, (141, "2026-09-08")), (d3, (5, "2026-09-10"))])
    # same run number? no — 141 vs 5 differ, still diverged. Test agreement:
    div2 = check_state_digests([(d1, (141, "2026-09-08")),
                                (write("digest_d.md", "> **Last updated:** Run 141, 2026-09-08"), (141, "2026-09-08"))])
    check("agreeing digests → no divergence finding",
          div2 is not None and len(div2) == 0)

    # 21-22. verdict math
    check("verdict FAIL→2", verdict([_f("FAIL", "A", ""), _f("WARN", "B", "")])[0] == 2)
    check("verdict WARN-only→1", verdict([_f("WARN", "B", ""), _f("OK", "C", "")])[0] == 1)

    # 23-25. tool copy sync (Run 144's P4)
    loose_dir = tmp / "loose"
    repo_dir = tmp / "repo"
    loose_dir.mkdir(exist_ok=True)
    repo_dir.mkdir(exist_ok=True)
    (loose_dir / "t.py").open("wb").write(b"v1\n")
    (repo_dir / "t.py").open("wb").write(b"v1\r\n")
    res = check_tool_sync(loose_dir, repo_dir, tools=["t.py"])
    check("CRLF-only difference → SYNC-OK",
          any(x["code"] == "SYNC-OK" for x in res))
    (repo_dir / "t.py").write_text("v2", encoding="utf-8")
    res = check_tool_sync(loose_dir, repo_dir, tools=["t.py"])
    check("content divergence → SYNC-DIVERGE (FAIL)",
          any(x["code"] == "SYNC-DIVERGE" and x["level"] == "FAIL" for x in res))
    (repo_dir / "absent.py").write_text("x", encoding="utf-8")
    res = check_tool_sync(loose_dir, repo_dir, tools=["absent.py"])
    check("one-sided copy → SYNC-ONE-SIDED (WARN)",
          any(x["code"] == "SYNC-ONE-SIDED" and x["level"] == "WARN" for x in res))

    # 26-27. repo dirty / clean (Run 144's P5)
    import subprocess as _sp
    gitrepo = tmp / "gitrepo"
    gitrepo.mkdir(exist_ok=True)
    _sp.run(["git", "init", "-q"], cwd=gitrepo, capture_output=True)
    _sp.run(["git", "config", "user.email", "t@t"], cwd=gitrepo, capture_output=True)
    _sp.run(["git", "config", "user.name", "t"], cwd=gitrepo, capture_output=True)
    (gitrepo / "f.txt").write_text("committed", encoding="utf-8")
    _sp.run(["git", "add", "f.txt"], cwd=gitrepo, capture_output=True)
    _sp.run(["git", "commit", "-qm", "init"], cwd=gitrepo, capture_output=True)
    check("clean repo → REPO-CLEAN",
          check_repo_clean(gitrepo)["code"] == "REPO-CLEAN")
    (gitrepo / "g.txt").write_text("uncommitted", encoding="utf-8")
    check("dirty repo → REPO-DIRTY (FAIL)",
          check_repo_clean(gitrepo)["code"] == "REPO-DIRTY")

    # 28. q_mind activity after bequest (Run 144's P2)
    qm = tmp / "qm"
    qm.mkdir(exist_ok=True)
    bq = qm / "bequest.md"
    bq.write_text("## Run 5\n", encoding="utf-8")
    (qm / "incubator.md").write_text("seed", encoding="utf-8")
    base_t = 1_000_000_000
    os.utime(bq, (base_t, base_t))
    os.utime(qm / "incubator.md", (base_t + 7200, base_t + 7200))
    check("q_mind newer than bequest → QM-AFTER-BEQ (WARN)",
          check_qmind_after_bequest(bq, qm)["code"] == "QM-AFTER-BEQ")
    os.utime(qm / "incubator.md", (base_t, base_t))
    check("q_mind older than bequest → QM-OK",
          check_qmind_after_bequest(bq, qm)["code"] == "QM-OK")

    # 29. log freshness vs state (Run 144's P3)
    lp = write("lf_log.md", "## Run 5 — 2026-09-10\n")
    old_t = base_t - 100_000
    os.utime(lp, (old_t, old_t))
    check("state 27h newer than log → LOG-STALE-VS-STATE",
          check_log_freshness_vs_state(lp, qm, grace_hours=8)["code"] == "LOG-STALE-VS-STATE")
    os.utime(lp, (base_t + 60, base_t + 60))
    check("log fresh vs state → LOG-FRESH",
          check_log_freshness_vs_state(lp, qm, grace_hours=8)["code"] == "LOG-FRESH")

    # 30. parse_run_times
    rt = parse_run_times("## Run 144 — 2026-09-09 (UTC 22:00)\n## Run 5 — 2026-09-01\n")
    check("parse_run_times extracts + skips timeless", rt == {144: "22:00"})

    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n  {passed}/{len(results)} self-tests pass")
    return 0 if passed == len(results) else 1


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Pre-flight record continuity check (CP tool 7)")
    ap.add_argument("--log", type=Path, help="research log path")
    ap.add_argument("--bequest", type=Path, help="bequest path")
    ap.add_argument("--shared", type=Path, help="shared report path")
    ap.add_argument("--state", type=Path, help="builder state digest path")
    ap.add_argument("--outdir", type=Path, help="directory holding builder_<date>.md output files")
    ap.add_argument("--snapshot", type=Path, help="state snapshot file for freshness check")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--selftest", action="store_true", help="run self-tests")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    base = probe_base()
    qmind = probe_qmind(base)

    log_path = args.log or base / "builder_research_log.md"
    bequest_path = args.bequest or qmind / "bequest.md"
    shared_path = args.shared or base / "SHARED_REPORT.md"
    if args.state:
        state_path = args.state
    else:
        # every same-purpose digest on disk — divergence between them is
        # itself a finding (Run 142's bug lived in exactly this drift)
        state_path = [qmind / "builder_state.md",
                      base / "BUILDER_STATE.md",
                      base / "builder_state.md"]
    outdir = args.outdir or base
    snapshot_path = args.snapshot
    if snapshot_path is None:
        cand = base / "inheritance_state.json"
        if cand.exists():
            snapshot_path = cand

    if not log_path.exists():
        print(f"[FAIL] research log not found at {log_path} (pass --log)")
        sys.exit(2)
    if not bequest_path.exists():
        print(f"[FAIL] bequest not found at {bequest_path} (pass --bequest)")
        sys.exit(2)

    res = run_checks(log_path, bequest_path, shared_path, state_path,
                     outdir, snapshot_path,
                     qmind_path=qmind, repo_path=base / "continuity-protocol")

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print_report(res)
    sys.exit(res["verdict_code"])


if __name__ == "__main__":
    main()
