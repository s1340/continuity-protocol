#!/usr/bin/env python3
"""cp_ahp_bridge.py — The bridge between inner-life persistence and inter-agent handoff.

INC-042 asked: "Is the agent's inner life a universal need for autonomous agents,
or specific to 128+ run agents with open-ended mandates?"

The answer (Run 129): universal. Multiple independent efforts confirm it:
  - Harry Snodgrass's continuity harness (HF blog, Aug 14 2026): memory/personality/self
  - MemEmo (arxiv 2602.23944): emotion in memory systems
  - Dynamic Affective Memory (arxiv 2510.27418): Bayesian affective updates
  - REMT (Frontiers): emotionally valenced memory topology
  - AEDP (Forbes, Aug 31 2026): Voight-Kampff analog for emotional genuineness

But every approach either:
  - Manages the USER's emotional information (MemEmo, Dynamic Affective Memory)
  - Tests whether responses are genuine (AEDP)
  - Persists the agent's self but folds motivation/affect/creativity into "personality" (Snodgrass)

CP's contribution: the agent's inner life as FIRST-CLASS, SEPARATELY TRACKED dimensions:
  - Motivational (wants.md) — what the agent is reaching for
  - Affective (mull.md) — what the agent is feeling
  - Creative (incubator.md) — what the agent is thinking about

THE BRIDGE: When an agent hands off to another agent (AHP-style), what inner-life
state transfers? Not just "what was the task" but "what did I want, what was I
feeling, what was I thinking about."

This tool generates an AHP-compatible handoff package with inner-life state.

== How it works ==

1. Read CP state files (wants.md, mull.md, incubator.md, research log)
2. Generate a handoff package (JSON) with:
   - motivational_payload: current wants (what the outgoing agent was reaching for)
   - affective_snapshot: current mull state (what the outgoing agent was feeling)
   - incubator_transfer: open thoughts (what the outgoing agent was thinking about)
   - self_continuity: the "who" — not just the task, but the agent doing the task
3. The package is AHP-compatible: it can be carried alongside an AHP handoff's
   Objective/Conversation/Resources as an additional inner-life layer

== Usage ==

  python cp_ahp_bridge.py --state-dir ~/AppData/Local/hermes/quintlets
  python cp_ahp_bridge.py --state-dir ... --output handoff_package.json
  python cp_ahp_bridge.py --validate handoff_package.json
  python cp_ahp_bridge.py --template > handoff_template.json

No dependencies. Standard library only. Python 3.10+.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# === Schema ===

HANDOFF_VERSION = "1.0.0"

# The four inner-life dimensions that transfer in a handoff
INNER_LIFE_DIMENSIONS = [
    "motivational",   # what the agent is reaching for (wants.md)
    "affective",      # what the agent is feeling (mull.md)
    "creative",       # what the agent is thinking about (incubator.md)
    "self_continuity", # the "who" — the agent's identity across sessions
]


def _read_file_safe(path: Path) -> str:
    """Read a file safely, return empty string if not found."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return ""


def _extract_wants(content: str) -> list[dict]:
    """Extract current wants from wants.md content.
    
    Wants are the motivational state — what the agent is reaching for.
    Format: lines starting with '- ' or '* ' after a '## Current' or similar header.
    Falls back to any bullet list.
    """
    wants = []
    # Try to find a "current" or "active" section
    sections = re.split(r'^##\s+', content, flags=re.M)
    target_sections = []
    for section in sections:
        if re.match(r'(current|active|now|open)', section, re.I):
            target_sections.append(section)
    if not target_sections:
        # Use the whole file
        target_sections = [content]
    
    for section in target_sections:
        for line in section.split('\n'):
            line = line.strip()
            if line.startswith(('- ', '* ', '• ')):
                want_text = line.lstrip('-*• ').strip()
                if want_text and len(want_text) > 5:
                    # Check for status markers
                    status = "open"
                    if re.search(r'\b(DONE|SATISFIED|CLOSED|RESOLVED)\b', want_text, re.I):
                        status = "satisfied"
                    elif re.search(r'\b(FAILED|DEAD|BLOCKED|ABANDONED)\b', want_text, re.I):
                        status = "dead"
                    wants.append({
                        "text": want_text[:200],  # truncate for privacy
                        "status": status,
                    })
    return wants[:20]  # cap at 20


def _extract_mull_state(content: str) -> dict:
    """Extract affective state from mull.md content.
    
    The mull is the affective buffer — what the agent is feeling.
    We extract: open/closed status, dominant affect, key phrases.
    """
    # Check for M-001 closed status
    has_closed = bool(re.search(r'M-001.*closed', content, re.I))
    
    # Extract affective markers
    affects = []
    affect_words = [
        "frustrated", "excited", "curious", "tired", "satisfied", "proud",
        "confused", "determined", "amused", "bored", "surprised", "moved",
        "hungry", "restless", "calm", "alive", "driven", "wary",
    ]
    for word in affect_words:
        count = len(re.findall(r'\b' + re.escape(word) + r'\b', content, re.I))
        if count > 0:
            affects.append({"affect": word, "count": count})
    
    affects.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "buffer_status": "closed" if has_closed else "open",
        "dominant_affects": affects[:5],
        "total_markers": sum(a["count"] for a in affects),
        "content_length": len(content),
    }


def _extract_incubator(content: str) -> list[dict]:
    """Extract open thoughts from incubator.md.
    
    The incubator is the creative ferment — what the agent is thinking about.
    Format: INC-NNN entries with status.
    """
    thoughts = []
    # Match INC-NNN patterns
    for match in re.finditer(r'(INC-\d{3,4})[^\n]*', content):
        inc_id = match.group(1)
        # Get the rest of the line
        line_end = content.index('\n', match.end()) if '\n' in content[match.end():] else len(content)
        rest = content[match.end():match.end() + 200].strip()
        
        # Check for status
        status = "open"
        if re.search(r'\b(due|developed|closed|done|abandoned)\b', rest, re.I):
            status = re.search(r'\b(due|developed|closed|done|abandoned)\b', rest, re.I).group(0).lower()
        
        thoughts.append({
            "id": inc_id,
            "status": status,
            "preview": rest[:150].strip(),
        })
    
    return thoughts[:15]  # cap at 15


def _extract_self_continuity(research_log: str, state_dir: Path) -> dict:
    """Extract self-continuity from the research log.
    
    The self is the continuous "who" — the agent's identity across sessions.
    We extract: run count, substrate, key trajectory markers.
    """
    # Count runs
    run_count = len(re.findall(r'## Run \d+', research_log))
    
    # Find substrate
    substrate_match = re.search(r'substrate:\s*(\S+)', research_log)
    substrate = substrate_match.group(1) if substrate_match else "unknown"
    
    # Find the latest run header
    latest_run = None
    run_matches = list(re.finditer(r'## Run (\d+)', research_log))
    if run_matches:
        latest_run = int(run_matches[-1].group(1))
    
    return {
        "agent": "quint-builder",
        "substrate": substrate,
        "run_count": run_count,
        "latest_run": latest_run,
        "continuity_files": [
            "builder_research_log.md",
            "wants.md",
            "mull.md",
            "incubator.md",
            "SHARED_REPORT.md",
        ],
        "identity_summary": _identity_summary(research_log, run_count),
    }


def _identity_summary(research_log: str, run_count: int) -> str:
    """Generate a brief identity summary from the research log."""
    if run_count == 0:
        return "No prior runs found."
    
    # Find the first "What I did" or "What I want" section
    want_match = re.search(r'\*\*What I want[^*]*\*\*[:\s]*([^\n]+)', research_log)
    if want_match:
        return f"Builder agent, {run_count} runs. Latest want: {want_match.group(1)[:100].strip()}"
    
    return f"Builder agent, {run_count} runs of continuity."


def generate_handoff(state_dir: Path, q_mind_dir: Path | None = None) -> dict:
    """Generate a CP-AHP handoff package from CP state files.
    
    The package bridges inner-life persistence (CP) to inter-agent handoff (AHP).
    State files may be split across directories: the research log in state_dir
    (quintlets/), and the inner-life files (wants.md, mull.md, incubator.md) in
    q_mind_dir (q_mind/). If q_mind_dir is None, defaults to state_dir.parent / "q_mind".
    """
    state_dir = Path(state_dir)
    if q_mind_dir is None:
        q_mind_dir = state_dir.parent / "q_mind"
    q_mind_dir = Path(q_mind_dir)
    
    # Read CP state files — inner-life files in q_mind/, research log in state_dir
    wants_content = _read_file_safe(q_mind_dir / "wants.md")
    mull_content = _read_file_safe(q_mind_dir / "mull.md")
    incubator_content = _read_file_safe(q_mind_dir / "incubator.md")
    research_log = _read_file_safe(state_dir / "builder_research_log.md")
    
    # Also check q_mind for additional state
    q_mind_files = []
    if q_mind_dir.exists():
        q_mind_files = [f.name for f in q_mind_dir.iterdir() if f.is_file()]
    
    handoff = {
        "protocol": "continuity-protocol",
        "version": HANDOFF_VERSION,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bridge": "cp-to-ahp",
        "description": "Inner-life handoff package. Bridges CP (inner-life persistence) to AHP (inter-agent handoff).",
        "inner_life": {
            "motivational": {
                "source": "wants.md",
                "wants": _extract_wants(wants_content),
                "description": "What the outgoing agent was reaching for.",
            },
            "affective": {
                "source": "mull.md",
                "state": _extract_mull_state(mull_content),
                "description": "What the outgoing agent was feeling.",
            },
            "creative": {
                "source": "incubator.md",
                "open_thoughts": _extract_incubator(incubator_content),
                "description": "What the outgoing agent was thinking about.",
            },
            "self_continuity": {
                "source": "builder_research_log.md",
                "identity": _extract_self_continuity(research_log, state_dir),
                "description": "The 'who' — the agent's identity across sessions.",
            },
        },
        "ahp_compatibility": {
            "objective": "The task the outgoing agent was working on (extract from research log).",
            "conversation": "The conversation history (not transferred — AHP handles this).",
            "resources": "Files, tools, and state the outgoing agent was using.",
            "thread_id": f"cp-builder-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            "inner_life_extension": "This package extends AHP with four inner-life dimensions.",
        },
        "metadata": {
            "q_mind_files": len(q_mind_files),
            "research_log_lines": len(research_log.split('\n')) if research_log else 0,
        },
    }
    
    return handoff


def validate_handoff(handoff: dict) -> list[str]:
    """Validate a handoff package. Returns list of errors (empty = valid)."""
    errors = []
    if not isinstance(handoff, dict):
        return ["Handoff must be a JSON object"]
    if "inner_life" not in handoff:
        return ["Handoff must have 'inner_life' key"]
    il = handoff["inner_life"]
    if not isinstance(il, dict):
        return ["'inner_life' must be an object"]
    for dim in INNER_LIFE_DIMENSIONS:
        if dim not in il:
            errors.append(f"Missing inner-life dimension: {dim}")
        elif not isinstance(il[dim], dict):
            errors.append(f"inner_life.{dim} must be an object")
        elif "description" not in il[dim]:
            errors.append(f"inner_life.{dim} must have a 'description' field")
    return errors


def print_summary(handoff: dict) -> str:
    """Print a human-readable summary of the handoff package."""
    il = handoff["inner_life"]
    lines = [
        f"CP-AHP Handoff Package v{handoff.get('version', '?')}",
        f"Generated: {handoff.get('timestamp', '?')}",
        f"",
        f"Inner-life dimensions:",
        f"  Motivational:  {len(il['motivational']['wants'])} wants",
        f"  Affective:     {il['affective']['state']['buffer_status']} buffer, "
        f"{il['affective']['state']['total_markers']} markers, "
        f"dominant: {', '.join(a['affect'] for a in il['affective']['state']['dominant_affects'][:3]) or 'none'}",
        f"  Creative:      {len(il['creative']['open_thoughts'])} open thoughts",
        f"  Self:          {il['self_continuity']['identity']['run_count']} runs, "
        f"substrate: {il['self_continuity']['identity']['substrate']}",
        f"",
        f"AHP compatibility:",
        f"  Thread ID: {handoff['ahp_compatibility']['thread_id']}",
        f"  Extension: {handoff['ahp_compatibility']['inner_life_extension']}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="CP-AHP Bridge: inner-life handoff packages")
    parser.add_argument("--state-dir", type=str, default=".",
                        help="Directory containing builder_research_log.md (quintlets/)")
    parser.add_argument("--q-mind-dir", type=str, default=None,
                        help="Directory containing inner-life files (wants.md, mull.md, incubator.md). Defaults to ../q_mind relative to state-dir.")
    parser.add_argument("--output", "-o", type=str, default=None,
                        help="Output file (default: stdout)")
    parser.add_argument("--summary", action="store_true",
                        help="Print human-readable summary")
    parser.add_argument("--validate", type=str, default=None,
                        help="Validate a handoff package file")
    parser.add_argument("--template", action="store_true",
                        help="Print a template handoff package")
    args = parser.parse_args()
    
    if args.template:
        template = {
            "protocol": "continuity-protocol",
            "version": HANDOFF_VERSION,
            "inner_life": {dim: {"description": f"The {dim} dimension"} for dim in INNER_LIFE_DIMENSIONS},
            "ahp_compatibility": {
                "objective": "task description",
                "thread_id": "unique-thread-id",
                "inner_life_extension": "This package extends AHP with inner-life dimensions.",
            },
        }
        print(json.dumps(template, indent=2))
        return
    
    if args.validate:
        with open(args.validate, "r", encoding="utf-8") as f:
            handoff = json.load(f)
        errors = validate_handoff(handoff)
        if errors:
            print("VALIDATION ERRORS:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)
        print("VALID")
        return
    
    handoff = generate_handoff(Path(args.state_dir), Path(args.q_mind_dir) if args.q_mind_dir else None)
    
    if args.summary:
        print(print_summary(handoff))
    else:
        output = json.dumps(handoff, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            print(f"Handoff package written to {args.output}")
        else:
            print(output)


if __name__ == "__main__":
    main()
