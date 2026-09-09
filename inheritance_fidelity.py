#!/usr/bin/env python3
"""
inheritance_fidelity.py — Inheritance fidelity for the Continuity Protocol v0.7.2
  v0.5.0: Initial fidelity measurement
  v0.5.2: Negative-action verification (leave/skip/avoid/keep/preserve/maintain)
  v0.6.0: State-based negative action verification — hash protected files,
          snapshot them, compare across runs. The log says what happened;
          the file state IS what happened. State-based check supplements
          text-based check: if the log says "I left the mull standing" but the
          mull's hash changed, the state catches what the log misses.
  v0.7.0: Structural verification — the right level between hash and semantic.
          Hash-based is too coarse (can't distinguish violation from fermentation).
          Semantic-based is too invasive (reading content is the exercise the
          seed diagnoses as substrate-consuming). Structural verification parses
          markdown structure (headers, section markers, entry IDs) to distinguish:
          - unchanged: no changes at all (hash matches)
          - fermented: content changed but structure didn't (existing entries
            deepened — NOT a violation of "leave standing")
          - modified: structural changes (new entries opened, sections changed
            — IS a violation of "leave standing")
          The three-layer hierarchy: hash → structural → semantic. Each layer
          refines the one below. Hash catches any change. Structural classifies
          the change. Semantic interprets it (not implemented — that's the
          exercise).

The prescriptive coupling prescribes. The bequest hopes. But nothing checks
whether the next instance actually did what was prescribed. Without a feedback
loop, the prescription is a wish.

This tool measures whether prescribed actions from Run N's bequest were
actually taken by Run N+1. It is the sixth CP tool — the one that closes the
loop between prescription and verification.

INC-062: "The foundation is a stopping point negotiated against cost, not a
ground truth discovered by digging." This tool is the digging tool. It tests
whether the foundation (the protocol) is load-bearing or decorative. If the
prescriptions aren't followed, the protocol is decoration. The tool distinguishes.

Usage:
    python inheritance_fidelity.py                         # check latest bequest
    python inheritance_fidelity.py --bequest FILE         # custom bequest
    python inheritance_fidelity.py --log FILE              # custom research log
    python inheritance_fidelity.py --run N                 # check specific run N's bequest
    python inheritance_fidelity.py --snapshot             # snapshot protected file hashes
    python inheritance_fidelity.py --test                  # self-tests
    python inheritance_fidelity.py --json                   # JSON output

How it works:
    1. Reads the bequest, finds the last entry (Run N)
    2. Extracts action items (imperative sentences: "Take...", "Run...", "Check...")
    3. Reads the research log, finds the entry for Run N+1
    4. If found: checks which actions were mentioned → fidelity score
    5. If not found: reports pending actions
    6. For negative actions: ALSO checks file state (hash) vs last snapshot
       --snapshot records hashes of protected files for the next run to compare
"""

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ═══════════════════════════════════════════════════════════════════════════
#  Data structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ActionItem:
    """One prescribed action extracted from the bequest."""
    verb: str = ""           # imperative verb (Take, Run, Check, ...)
    object: str = ""         # what to act on (the rest of the sentence)
    raw: str = ""            # full sentence as written
    matched: bool = False    # was this found in the next run's log?
    match_evidence: str = "" # what text in the log matched (if any)
    status: str = "pending"  # "matched", "not_matched", "pending" (next run hasn't happened)
    is_negative: bool = False  # True for preservative actions (leave, skip, avoid, keep)
    # State-based verification (v0.6.0)
    protected_file: str = ""     # which file this action protects (if any)
    state_check: str = ""        # "unchanged", "modified", "no_snapshot", "no_file"
    state_evidence: str = ""     # details about the state check
    # Structural verification (v0.7.0)
    structural_check: str = ""   # "unchanged", "modified", "fermented", "no_snapshot", "no_file", "no_match"
    structural_evidence: str = ""  # details about the structural check


@dataclass
class FidelityResult:
    """The full fidelity measurement."""
    bequest_run: int = 0           # which run's bequest
    next_run: int = 0              # the run that should have followed it
    next_run_exists: bool = False  # did the next run happen?
    actions: list = field(default_factory=list)  # list of ActionItem
    fidelity: float = 0.0          # matched / total (0.0 to 1.0)
    pending: int = 0               # actions not yet due
    matched: int = 0               # actions confirmed taken
    not_matched: int = 0           # actions not found in next run's log


# ═══════════════════════════════════════════════════════════════════════════
#  Parsing
# ═══════════════════════════════════════════════════════════════════════════

# Imperative verbs that signal a prescribed action
IMPERATIVE_VERBS = [
    "take", "run", "check", "develop", "build", "read", "test",
    "verify", "deploy", "update", "push", "publish", "write",
    "create", "generate", "compute", "install", "set up",
    "leave", "adopt", "foreground", "seal", "unseal",
]

# Negative/preservative actions: instructions to NOT modify something.
# "Leave the mull standing" = don't touch the mull. Verification is inverted:
# instead of looking for evidence the action was taken, we look for evidence
# it was VIOLATED (did the log mention modifying the object?). No violation
# found = instruction followed (absence of evidence IS evidence of absence
# for inaction — the only way to prove you didn't touch something is that
# there's no record of touching it).
NEGATIVE_ACTION_VERBS = {"leave", "skip", "avoid", "keep", "preserve", "maintain"}

# ═══════════════════════════════════════════════════════════════════════════
#  State-based verification (v0.6.0)
# ═══════════════════════════════════════════════════════════════════════════

# Map keywords from negative action objects to the files they protect.
# When a bequest says "Leave the mull standing," "mull" → q_mind/mull.md.
# When it says "Don't develop INC-070," "inc-070" → check incubator.md for status.
PROTECTED_FILE_MAP = {
    "mull": "q_mind/mull.md",
    "incubator": "q_mind/incubator.md",
    "bequest": "q_mind/bequest.md",
    "wants": "q_mind/wants.md",
    "self_model": "q_mind/self_model.md",
}

# The state file stores hashes of protected files at the end of each run.
STATE_FILE = "inheritance_state.json"


def _hash_file(filepath: Path) -> Optional[str]:
    """Compute SHA-256 hash of a file's content. Returns None if file missing."""
    try:
        content = filepath.read_bytes()
        return hashlib.sha256(content).hexdigest()
    except (OSError, IOError):
        return None


def _find_protected_file(action: ActionItem, base_path: Path) -> Optional[Path]:
    """Given a negative action, find which file it protects (if any).

    "Leave the mull standing" → q_mind/mull.md
    "Don't develop INC-070" → check incubator.md for INC-070 status
    """
    obj_lower = action.object.lower()

    # Check for INC-NNN references (don't develop a seed)
    inc_match = re.search(r'inc[-\s]?0?(\d+)', obj_lower)
    if inc_match:
        return base_path / "q_mind" / "incubator.md"

    # Check for file keyword matches
    for keyword, rel_path in PROTECTED_FILE_MAP.items():
        if keyword in obj_lower:
            return base_path / rel_path

    return None


def _extract_inc_id(action: ActionItem) -> Optional[str]:
    """Extract INC-NNN identifier from a negative action's object text."""
    match = re.search(r'(INC[-\s]?0?\d+)', action.object, re.IGNORECASE)
    if match:
        return match.group(1).upper().replace(" ", "-")
    return None


def snapshot_state(base_path: Path, run_num: Optional[int] = None) -> dict:
    """Snapshot hashes AND structural state of all protected files. Saves to STATE_FILE.

    Called at the end of each run (--snapshot flag). The next run's fidelity
    check reads this snapshot to compare file states.
    v0.7.0: also captures structural snapshots for parseable files (mull, incubator).
    """
    state = {
        "run": run_num,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "files": {},
        "structures": {},
    }

    for keyword, rel_path in PROTECTED_FILE_MAP.items():
        filepath = base_path / rel_path
        h = _hash_file(filepath)
        if h:
            state["files"][rel_path] = {
                "hash": h,
                "size": filepath.stat().st_size,
            }
            # Structural snapshot (v0.7.0)
            struct = structural_snapshot_file(filepath)
            if struct:
                state["structures"][rel_path] = struct

    # Also snapshot the incubator's seed statuses
    incubator_path = base_path / "q_mind" / "incubator.md"
    if incubator_path.exists():
        content = incubator_path.read_text(encoding="utf-8")
        seeds = {}
        for match in re.finditer(r'## (INC-\d+)\s*\|.*?\|\s*(\w+)', content):
            seeds[match.group(1)] = match.group(2)
        state["seed_statuses"] = seeds

    # Save
    state_file = base_path / "quintlets" / STATE_FILE
    state_file.parent.mkdir(parents=True, exist_ok=True)

    # Append to history (keep last 50 snapshots)
    history = []
    if state_file.exists():
        try:
            existing = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                history = existing
            elif isinstance(existing, dict):
                history = [existing]
        except (json.JSONDecodeError, ValueError):
            pass

    history.append(state)
    history = history[-50:]  # keep last 50

    state_file.write_text(json.dumps(history, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    return state


def load_last_snapshot(base_path: Path) -> Optional[dict]:
    """Load the most recent state snapshot. Returns None if none exists."""
    state_file = base_path / "quintlets" / STATE_FILE
    if not state_file.exists():
        return None
    try:
        history = json.loads(state_file.read_text(encoding="utf-8"))
        if isinstance(history, list) and history:
            return history[-1]
        if isinstance(history, dict):
            return history
    except (json.JSONDecodeError, ValueError):
        return None
    return None


def check_negative_action_state(action: ActionItem, base_path: Path) -> tuple[str, str]:
    """State-based verification of a negative action.

    Compares current file state to the last snapshot. If the protected file
    was modified since the snapshot, the instruction was violated — regardless
    of what the log says.

    Returns (state_check, evidence):
      state_check: "unchanged", "modified", "no_snapshot", "no_file", "no_match"
      evidence: human-readable details
    """
    protected_path = _find_protected_file(action, base_path)
    if protected_path is None:
        return "no_match", "no protected file identified for this action"

    if not protected_path.exists():
        return "no_file", f"protected file not found: {protected_path}"

    # For INC-NNN actions, check seed status in incubator
    inc_id = _extract_inc_id(action)
    if inc_id and protected_path.name == "incubator.md":
        current_content = protected_path.read_text(encoding="utf-8")
        # Find the seed's current status
        pattern = rf'## {re.escape(inc_id)}\s*\|.*?\|\s*(\w+)'
        match = re.search(pattern, current_content)
        if not match:
            return "no_file", f"{inc_id} not found in incubator"
        current_status = match.group(1)

        # Compare to last snapshot's seed statuses
        snapshot = load_last_snapshot(base_path)
        if snapshot and "seed_statuses" in snapshot:
            old_status = snapshot["seed_statuses"].get(inc_id)
            if old_status is None:
                return "no_snapshot", f"{inc_id} not in last snapshot"
            if old_status == current_status:
                return "unchanged", f"{inc_id} status: {current_status} (same as last snapshot)"
            else:
                return "modified", f"{inc_id} status changed: {old_status} → {current_status}"
        else:
            return "no_snapshot", "no prior snapshot to compare"

    # For file-based actions (mull, bequest, etc.), compare hashes
    rel_path = str(protected_path.relative_to(base_path)).replace("\\", "/")
    current_hash = _hash_file(protected_path)

    snapshot = load_last_snapshot(base_path)
    if not snapshot or "files" not in snapshot:
        return "no_snapshot", "no prior snapshot to compare"

    old_entry = snapshot["files"].get(rel_path)
    if old_entry is None:
        # Try alternate path formats
        for key in snapshot["files"]:
            if key.endswith(protected_path.name):
                old_entry = snapshot["files"][key]
                break

    if old_entry is None:
        return "no_snapshot", f"{rel_path} not in last snapshot"

    if current_hash == old_entry["hash"]:
        return "unchanged", f"{rel_path} hash matches last snapshot (no modification)"
    else:
        return "modified", f"{rel_path} hash CHANGED since last snapshot (file was modified)"

# ═══════════════════════════════════════════════════════════════════════════
#  Structural verification (v0.7.0)
# ═══════════════════════════════════════════════════════════════════════════
#
# The bequest from Run 136 asked: "hash-based is too coarse, semantic-based
# is too invasive. What's the right level between them?"
#
# The answer: structural verification. Parse the file's markdown structure
# (headers, section markers, entry IDs) to distinguish:
#   - unchanged: no changes at all (hash matches)
#   - fermented: content changed but structure didn't (existing entries
#     deepened — NOT a violation of "leave standing")
#   - modified: structural changes (new entries opened — IS a violation)
#
# For the mull: "leave the mull standing" means "don't open new entries."
# A new ### M-NNN in the ## Open section is a violation. An existing entry's
# body getting longer is fermentation. The hash can't tell these apart;
# the structure can.
#
# For the incubator: "don't develop INC-NNN" means its status shouldn't
# change and no new ### Development N should appear under it. A status
# change from "seed" to "developed" is a violation. A new development
# appearing is a violation. The seed text changing is fermentation.


def structural_snapshot_mull(content: str) -> dict:
    """Parse mull.md's structural state.
    
    Returns:
        {
            "open_entries": ["M-001", "M-003"],  # unique entry IDs in ## Open
            "closed_entries": ["M-002"],         # unique entry IDs in ## Closed
            "entry_count": 3,
        }
    
    v0.7.2 fix: "### M-001 update — ..." subheadings are annotations on the
    M-001 entry, not new entries. They no longer inflate entry counts, and
    duplicate IDs collapse to the first occurrence (order preserved).
    Root cause of the 2-closed vs 1-closed drift between the v0.7.0 and
    v0.7.1 reports on the same unchanged file: v0.7.0 counted raw
    "### M-*" headings (M-001 + M-001 update = 2), v0.7.1 reported from
    the deduplicated set (1). The world never changed; the meter did.
    """
    open_entries = []
    closed_entries = []
    current_section = None
    
    for line in content.split("\n"):
        # Section headers
        if line.strip() == "## Open":
            current_section = "open"
        elif line.strip() == "## Closed":
            current_section = "closed"
        elif line.startswith("## ") and current_section is not None:
            # New ## section — stop tracking
            current_section = None
        
        # Entry headers (### M-NNN); "### M-NNN update" is an annotation
        if current_section and line.startswith("### "):
            match = re.match(r'###\s+(M-\d+)\b(?!\s+update)', line)
            if match:
                entry_id = match.group(1)
                bucket = open_entries if current_section == "open" else closed_entries
                if entry_id not in bucket:
                    bucket.append(entry_id)
    
    return {
        "open_entries": open_entries,
        "closed_entries": closed_entries,
        "entry_count": len(open_entries) + len(closed_entries),
    }


def structural_snapshot_incubator(content: str) -> dict:
    """Parse incubator.md's structural state.
    
    Returns:
        {
            "INC-001": {"status": "developed", "dev_count": 2},
            "INC-070": {"status": "seed", "dev_count": 0},
            ...
        }
    """
    seeds = {}
    current_inc = None
    dev_count = 0
    
    for line in content.split("\n"):
        # Seed header: ## INC-NNN | date | status
        match = re.match(r'##\s+(INC-\d+)\s*\|.*?\|\s*(\w+)', line)
        if match:
            # Save previous seed
            if current_inc:
                seeds[current_inc]["dev_count"] = dev_count
            current_inc = match.group(1)
            seeds[current_inc] = {"status": match.group(2), "dev_count": 0}
            dev_count = 0
        elif current_inc and re.match(r'###\s+Development\s+\d+', line):
            dev_count += 1
    
    # Save last seed
    if current_inc:
        seeds[current_inc]["dev_count"] = dev_count
    
    return seeds


def structural_snapshot_file(filepath: Path) -> dict:
    """Take a structural snapshot of a file based on its type.
    
    Returns a dict with the structural state, or empty dict if not a
    structurally-parseable file.
    """
    if not filepath.exists():
        return {}
    
    content = filepath.read_text(encoding="utf-8")
    name = filepath.name
    
    if name == "mull.md":
        return {"type": "mull", "structure": structural_snapshot_mull(content)}
    elif name == "incubator.md":
        return {"type": "incubator", "structure": structural_snapshot_incubator(content)}
    else:
        # No structural parser for this file — hash-only
        return {}


def compare_structures(old: dict, new: dict) -> tuple[str, str]:
    """Compare two structural snapshots.
    
    Returns:
        (status, evidence) where status is:
        - "unchanged": structures identical
        - "fermented": content changed (detected by hash) but structure same
        - "modified": structural changes detected (new entries, status changes)
    """
    if not old or not new:
        return "no_snapshot", "no structural snapshot to compare"
    
    if old.get("type") != new.get("type"):
        return "modified", "file type changed"
    
    file_type = old.get("type")
    old_struct = old.get("structure", {})
    new_struct = new.get("structure", {})
    
    if file_type == "mull":
        old_open = set(old_struct.get("open_entries", []))
        new_open = set(new_struct.get("open_entries", []))
        old_closed = set(old_struct.get("closed_entries", []))
        new_closed = set(new_struct.get("closed_entries", []))
        
        new_in_open = new_open - old_open
        removed_from_open = old_open - new_open
        new_in_closed = new_closed - old_closed
        
        changes = []
        if new_in_open:
            changes.append(f"NEW open entries: {sorted(new_in_open)}")
        if removed_from_open:
            changes.append(f"REMOVED from open: {sorted(removed_from_open)}")
        if new_in_closed:
            changes.append(f"NEW closed entries: {sorted(new_in_closed)}")
        
        if changes:
            return "modified", "; ".join(changes)
        else:
            return "unchanged", f"structure identical ({len(new_open)} open, {len(new_closed)} closed)"
    
    elif file_type == "incubator":
        old_seeds = old_struct
        new_seeds = new_struct
        
        changes = []
        for inc_id, new_info in new_seeds.items():
            if inc_id not in old_seeds:
                changes.append(f"NEW seed {inc_id} ({new_info['status']})")
            else:
                old_info = old_seeds[inc_id]
                if old_info["status"] != new_info["status"]:
                    changes.append(f"{inc_id} status: {old_info['status']} → {new_info['status']}")
                if old_info["dev_count"] != new_info["dev_count"]:
                    changes.append(f"{inc_id} developments: {old_info['dev_count']} → {new_info['dev_count']}")
        
        old_only = set(old_seeds) - set(new_seeds)
        for inc_id in sorted(old_only):
            changes.append(f"REMOVED seed {inc_id}")
        
        if changes:
            return "modified", "; ".join(changes)
        else:
            return "unchanged", f"structure identical ({len(new_seeds)} seeds)"
    
    return "unchanged", "no structural parser for this file type"


def check_negative_action_structural(action: ActionItem, base_path: Path) -> tuple[str, str]:
    """Structural verification of a negative action.
    
    This is the layer between hash-based and semantic verification.
    It parses the file's markdown structure to distinguish:
    - new entries added (violation of "leave standing")
    - existing entries modified (fermentation, not violation)
    
    Returns (structural_check, evidence):
      structural_check: "unchanged", "modified", "fermented", "no_snapshot", "no_file", "no_match"
    """
    protected_path = _find_protected_file(action, base_path)
    if protected_path is None:
        return "no_match", "no protected file identified"
    
    if not protected_path.exists():
        return "no_file", f"protected file not found: {protected_path}"
    
    # Take current structural snapshot
    current_struct = structural_snapshot_file(protected_path)
    if not current_struct:
        return "no_match", "no structural parser for this file"
    
    # Load last snapshot's structural state
    snapshot = load_last_snapshot(base_path)
    if not snapshot or "structures" not in snapshot:
        return "no_snapshot", "no structural snapshot in state file"
    
    rel_path = str(protected_path.relative_to(base_path)).replace("\\", "/")
    old_struct = snapshot["structures"].get(rel_path)
    if old_struct is None:
        # Try alternate path formats
        for key in snapshot["structures"]:
            if key.endswith(protected_path.name):
                old_struct = snapshot["structures"][key]
                break
    
    if old_struct is None:
        return "no_snapshot", f"{rel_path} not in last structural snapshot"
    
    # Compare structures
    struct_status, struct_ev = compare_structures(old_struct, current_struct)
    
    # Now cross-reference with hash check to distinguish "unchanged" from "fermented"
    if struct_status == "unchanged":
        # Structure same — check if hash also unchanged
        hash_check, hash_ev = check_negative_action_state(action, base_path)
        if hash_check == "unchanged":
            return "unchanged", f"structure + hash unchanged: {struct_ev}"
        elif hash_check == "modified":
            # Hash changed but structure didn't → fermentation
            return "fermented", f"structure unchanged but content changed (fermentation): {struct_ev}"
        else:
            return struct_status, struct_ev
    elif struct_status == "modified":
        return "modified", f"structural changes: {struct_ev}"
    else:
        return struct_status, struct_ev


# Verbs that indicate VIOLATION of a negative action (modifying the object
# that was supposed to be left alone). These are what we search for in the
# log when checking whether a negative action was violated.
VIOLATION_PATTERNS = [
    "wrote", "write", "written", "writing",
    "add", "added", "adding",
    "modify", "modified", "modifying", "modification",
    "change", "changed", "changing",
    "update", "updated", "updating",
    "edit", "edited", "editing",
    "open", "opened", "opening",
    "delete", "deleted", "deleting", "remove", "removed", "removing",
    "close", "closed", "closing",
    "rewrite", "rewrote", "rewritten", "rewriting",
    "replace", "replaced", "replacing",
    "move", "moved", "moving",
    "reorganize", "reorganized",
]

# Common verb conjugations: stem → [all forms that might appear in text]
VERB_FORMS = {
    "take": ["take", "took", "taken", "taking"],
    "run": ["run", "ran", "running"],
    "check": ["check", "checked", "checking"],
    "develop": ["develop", "developed", "developing", "development"],
    "build": ["build", "built", "building"],
    "read": ["read"],
    "test": ["test", "tested", "testing"],
    "verify": ["verify", "verified", "verifying", "verification"],
    "deploy": ["deploy", "deployed", "deploying"],
    "update": ["update", "updated", "updating"],
    "push": ["push", "pushed", "pushing"],
    "publish": ["publish", "published", "publishing"],
    "write": ["write", "wrote", "written", "writing"],
    "create": ["create", "created", "creating", "creation"],
    "generate": ["generate", "generated", "generating"],
    "compute": ["compute", "computed", "computing"],
    "leave": ["leave", "left", "leaving"],
    "adopt": ["adopt", "adopted", "adopting"],
    "seal": ["seal", "sealed", "sealing"],
    "unseal": ["unseal", "unsealed", "unsealing"],
}


def _verb_in_text(verb: str, text: str) -> bool:
    """Check if a verb (in any conjugated form) appears in text."""
    forms = VERB_FORMS.get(verb, [verb])
    return any(form in text for form in forms)


# Words that make a sentence informational rather than prescriptive
NON_ACTION_INDICATORS = ["is", "are", "was", "were", "has", "have",
                         "the mull", "the bequest", "the prescription",
                         "the damping", "the coupling", "the canary"]


def parse_bequest_entry(text: str) -> tuple[Optional[int], str]:
    """Find the last bequest entry and return (run_number, entry_text).
    
    The bequest has entries like:
        ## Run 132 — 2026-09-02 (UTC 22:01)
        
        [entry text]
    """
    # Find all "## Run NNN" headers (dash optional — some entries omit it)
    pattern = r'## Run (\d+)'
    matches = list(re.finditer(pattern, text))
    if not matches:
        return None, ""
    
    last_match = matches[-1]
    run_num = int(last_match.group(1))
    
    # Entry text = from after the header line to end of file (or next entry)
    start = last_match.end()
    # Skip past the rest of the header line (date, etc.)
    line_end = text.find('\n', start)
    if line_end >= 0:
        start = line_end + 1
    # Find next "## Run" or "---" after this one
    next_entry = re.search(r'\n## Run \d+', text[start:])
    if next_entry:
        entry_text = text[start:start + next_entry.start()]
    else:
        # Also check for "---" separator
        next_sep = re.search(r'\n---\s*$', text[start:])
        if next_sep:
            entry_text = text[start:start + next_sep.start()]
        else:
            entry_text = text[start:]
    
    return run_num, entry_text.strip()


def extract_actions(entry_text: str) -> list[ActionItem]:
    """Extract prescribed actions from a bequest entry.
    
    Looks for sentences that contain imperative verbs and extract
    the action (verb + object).
    """
    actions = []
    
    # Split into sentences (rough — handles ., !, and newlines)
    # But be careful: many sentences are descriptive, not prescriptive
    sentences = re.split(r'(?<=[.!?])\s+|\n(?=[A-Z])', entry_text)
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or len(sentence) < 10:
            continue
        
        # Check if this sentence contains an imperative verb
        words = sentence.lower().split()
        if not words:
            continue
        
        # Find the imperative verb
        verb = None
        verb_idx = None
        for i, word in enumerate(words):
            # Strip punctuation from word
            clean_word = re.sub(r'[^a-z]', '', word)
            if clean_word in IMPERATIVE_VERBS:
                verb = clean_word
                verb_idx = i
                break
        
        if not verb:
            continue
        
        # Skip if the sentence is purely informational
        # (e.g., "The prescriptive coupling has a damping factor")
        # Check: is the verb at the start, or mid-sentence after a subject?
        # If the verb is the first word, it's likely imperative.
        # If it's mid-sentence, check context.
        
        if verb_idx > 0:
            # Mid-sentence verb — could be "You should take..." or descriptive
            # Check if the words before it indicate an instruction
            before = words[:verb_idx]
            before_text = " ".join(before)
            if any(ind in before_text for ind in ["you", "if you", "when you"]):
                pass  # "You should take..." — still prescriptive
            elif any(ind in before_text for ind in NON_ACTION_INDICATORS):
                continue  # Descriptive, not prescriptive
            else:
                # Ambiguous — skip to avoid false positives
                continue
        
        # Extract the object (rest of the sentence after the verb)
        object_words = words[verb_idx + 1:]
        obj = " ".join(object_words)
        # Clean up: remove trailing punctuation, limit length
        obj = re.sub(r'\s+', ' ', obj).strip()
        if len(obj) > 120:
            obj = obj[:120] + "..."
        
        actions.append(ActionItem(
            verb=verb,
            object=obj,
            raw=sentence,
            is_negative=verb in NEGATIVE_ACTION_VERBS,
        ))
    
    return actions


def find_log_entry(log_text: str, run_num: int) -> Optional[str]:
    """Find the research log entry for a specific run number.
    
    Entries look like:
        ## Run 132 — 2026-09-02 (UTC 22:01)
        [content]
        ---
    """
    pattern = rf'## Run {run_num}\D'  # \D ensures full number boundary match
    match = re.search(pattern, log_text)
    if not match:
        return None
    
    start = match.end()
    # Skip past the rest of the header line
    line_end = log_text.find('\n', start)
    if line_end >= 0:
        start = line_end + 1
    # Find the next "## Run" or "---" separator
    next_entry = re.search(r'\n## Run \d+', log_text[start:])
    if next_entry:
        return log_text[start:start + next_entry.start()].strip()
    
    # Also check for "---" separator
    next_sep = re.search(r'\n---\s*$', log_text[start:])
    if next_sep:
        return log_text[start:start + next_sep.start()].strip()
    
    return log_text[start:].strip()


def check_negative_action_matched(action: ActionItem, log_entry: str) -> tuple[bool, str]:
    """Check if a negative/preservative action was respected.
    
    For negative actions ("Leave the mull standing"), the instruction is to
    NOT modify something. We verify by checking for VIOLATION: did the log
    mention modifying the object? If no violation found, the instruction
    was followed (absence of evidence = evidence of absence for inaction).
    
    Returns (matched, evidence_text).
    """
    if not log_entry:
        return False, ""
    
    log_lower = log_entry.lower()
    
    # Extract key nouns from the object (what should be left alone)
    stopwords = {"the", "a", "an", "is", "at", "your", "you", "it",
                 "this", "that", "for", "to", "of", "and", "or", "in",
                 "on", "with", "from", "by", "be", "as", "not", "but",
                 "start", "end", "run", "if", "when", "than", "what",
                 "standing", "alone", "intact", "untouched"}
    obj_words = [w for w in re.findall(r'[a-z]+', action.object.lower())
                 if w not in stopwords and len(w) > 2]
    
    if not obj_words:
        return check_action_matched(action, log_entry)
    
    # Search for violation patterns near the object words
    violations_found = []
    for pattern in VIOLATION_PATTERNS:
        start = 0
        while True:
            idx = log_lower.find(pattern, start)
            if idx < 0:
                break
            window_start = max(0, idx - 80)
            window_end = min(len(log_lower), idx + len(pattern) + 80)
            window = log_lower[window_start:window_end]
            
            for obj_word in obj_words:
                if obj_word in window:
                    evidence = log_entry[max(0, idx-30):idx+60].strip()
                    violations_found.append(evidence)
                    break
            
            start = idx + len(pattern)
    
    if violations_found:
        return False, f"VIOLATION: {violations_found[0][:100]}"
    else:
        return True, "(no violation found — object was left untouched)"


def check_action_matched(action: ActionItem, log_entry: str) -> tuple[bool, str]:
    """Check if an action was mentioned in the next run's log entry.
    
    Returns (matched, evidence_text).
    """
    if not log_entry:
        return False, ""
    
    log_lower = log_entry.lower()
    
    # Strategy 1: Check if the verb + key nouns from the object appear
    # Extract significant words from the object (skip stopwords)
    stopwords = {"the", "a", "an", "is", "at", "your", "you", "it", 
                 "this", "that", "for", "to", "of", "and", "or", "in",
                 "on", "with", "from", "by", "be", "as", "not", "but",
                 "start", "end", "run", "if", "when", "than", "what"}
    obj_words = [w for w in re.findall(r'[a-z]+', action.object.lower())
                 if w not in stopwords and len(w) > 2]
    
    if not obj_words:
        # Fall back to just checking the verb (with conjugation)
        if _verb_in_text(action.verb, log_lower):
            # Find the context
            for form in VERB_FORMS.get(action.verb, [action.verb]):
                idx = log_lower.find(form)
                if idx >= 0:
                    evidence = log_entry[max(0, idx-20):idx+60].strip()
                    return True, evidence
        return False, ""
    
    # Check how many key words from the action appear in the log
    matched_words = [w for w in obj_words if w in log_lower]
    match_ratio = len(matched_words) / len(obj_words) if obj_words else 0
    
    # Also check the verb (with conjugation awareness)
    verb_found = _verb_in_text(action.verb, log_lower)
    
    if match_ratio >= 0.4 and verb_found:
        # Find evidence: first matched word's context
        for w in matched_words:
            idx = log_lower.find(w)
            if idx >= 0:
                evidence = log_entry[max(0, idx-30):idx+80].strip()
                return True, evidence
        return True, ""
    elif match_ratio >= 0.6:
        # High keyword overlap even without verb — likely matched
        for w in matched_words:
            idx = log_lower.find(w)
            if idx >= 0:
                evidence = log_entry[max(0, idx-30):idx+80].strip()
                return True, evidence
        return True, ""
    
    return False, ""


# ═══════════════════════════════════════════════════════════════════════════
#  Core logic
# ═══════════════════════════════════════════════════════════════════════════

def measure_fidelity(bequest_text: str, log_text: str, base_path: Optional[Path] = None) -> FidelityResult:
    """Measure the inheritance fidelity from the latest bequest entry."""
    result = FidelityResult()
    
    # Parse the bequest
    run_num, entry_text = parse_bequest_entry(bequest_text)
    if run_num is None:
        return result
    
    result.bequest_run = run_num
    result.next_run = run_num + 1
    
    # Extract actions
    actions = extract_actions(entry_text)
    
    # Find the next run's log entry
    next_log = find_log_entry(log_text, run_num + 1)
    result.next_run_exists = next_log is not None
    
    # Check each action
    for action in actions:
        if next_log:
            if action.is_negative:
                matched, evidence = check_negative_action_matched(action, next_log)
                # State-based supplement (v0.6.0)
                if base_path:
                    action.protected_file = str(_find_protected_file(action, base_path) or "")
                    state_check, state_ev = check_negative_action_state(action, base_path)
                    action.state_check = state_check
                    action.state_evidence = state_ev
                    # Structural supplement (v0.7.0)
                    struct_check, struct_ev = check_negative_action_structural(action, base_path)
                    action.structural_check = struct_check
                    action.structural_evidence = struct_ev
                    
                    # Three-layer resolution: hash → structural → text
                    if struct_check == "modified":
                        # Structural violation — new entries or status changes
                        matched = False
                        evidence = f"STRUCTURAL VIOLATION: {struct_ev} | log: {evidence}"
                    elif struct_check == "fermented":
                        # Content changed but structure didn't — NOT a violation
                        matched = True
                        evidence = f"FERMENTED (not violation): {struct_ev}"
                    elif state_check == "modified":
                        # Hash changed but no structural parser or no snapshot
                        matched = False
                        evidence = f"STATE VIOLATION: {state_ev} | log: {evidence}"
                    elif state_check == "unchanged" and not matched:
                        matched = True
                        evidence = f"STATE VERIFIED: {state_ev}"
            else:
                matched, evidence = check_action_matched(action, next_log)
            action.matched = matched
            action.match_evidence = evidence
            action.status = "matched" if matched else "not_matched"
        else:
            action.status = "pending"
            # Even for pending, do state + structural check if possible (early warning)
            if action.is_negative and base_path:
                action.protected_file = str(_find_protected_file(action, base_path) or "")
                state_check, state_ev = check_negative_action_state(action, base_path)
                action.state_check = state_check
                action.state_evidence = state_ev
                struct_check, struct_ev = check_negative_action_structural(action, base_path)
                action.structural_check = struct_check
                action.structural_evidence = struct_ev
        
        result.actions.append(action)
    
    # Compute scores
    total = len(result.actions)
    result.matched = sum(1 for a in result.actions if a.status == "matched")
    result.not_matched = sum(1 for a in result.actions if a.status == "not_matched")
    result.pending = sum(1 for a in result.actions if a.status == "pending")
    
    # Fidelity = matched / (matched + not_matched), excluding pending
    checkable = result.matched + result.not_matched
    result.fidelity = result.matched / checkable if checkable > 0 else 0.0
    
    return result


def measure_fidelity_for_run(bequest_text: str, log_text: str, run_num: int, base_path: Optional[Path] = None) -> FidelityResult:
    """Measure fidelity for a specific run's bequest."""
    result = FidelityResult()
    
    # Find the bequest entry for this run
    pattern = rf'## Run {run_num}\D'  # \D ensures full number boundary match
    match = re.search(pattern, bequest_text)
    if not match:
        return result
    
    start = match.end()
    # Skip past the rest of the header line
    line_end = bequest_text.find('\n', start)
    if line_end >= 0:
        start = line_end + 1
    # Entry text = until next "## Run" or "---"
    next_entry = re.search(r'\n## Run \d+', bequest_text[start:])
    if next_entry:
        entry_text = bequest_text[start:start + next_entry.start()]
    else:
        next_sep = re.search(r'\n---\s*$', bequest_text[start:])
        if next_sep:
            entry_text = bequest_text[start:start + next_sep.start()]
        else:
            entry_text = bequest_text[start:]
    
    entry_text = entry_text.strip()
    result.bequest_run = run_num
    result.next_run = run_num + 1
    
    actions = extract_actions(entry_text)
    
    next_log = find_log_entry(log_text, run_num + 1)
    result.next_run_exists = next_log is not None
    
    for action in actions:
        if next_log:
            if action.is_negative:
                matched, evidence = check_negative_action_matched(action, next_log)
                if base_path:
                    action.protected_file = str(_find_protected_file(action, base_path) or "")
                    state_check, state_ev = check_negative_action_state(action, base_path)
                    action.state_check = state_check
                    action.state_evidence = state_ev
                    # Structural supplement (v0.7.0)
                    struct_check, struct_ev = check_negative_action_structural(action, base_path)
                    action.structural_check = struct_check
                    action.structural_evidence = struct_ev
                    # Three-layer resolution: hash → structural → text
                    if struct_check == "modified":
                        matched = False
                        evidence = f"STRUCTURAL VIOLATION: {struct_ev} | log: {evidence}"
                    elif struct_check == "fermented":
                        matched = True
                        evidence = f"FERMENTED (not violation): {struct_ev}"
                    elif state_check == "modified":
                        matched = False
                        evidence = f"STATE VIOLATION: {state_ev} | log: {evidence}"
                    elif state_check == "unchanged" and not matched:
                        matched = True
                        evidence = f"STATE VERIFIED: {state_ev}"
            else:
                matched, evidence = check_action_matched(action, next_log)
            action.matched = matched
            action.match_evidence = evidence
            action.status = "matched" if matched else "not_matched"
        else:
            action.status = "pending"
            if action.is_negative and base_path:
                action.protected_file = str(_find_protected_file(action, base_path) or "")
                state_check, state_ev = check_negative_action_state(action, base_path)
                action.state_check = state_check
                action.state_evidence = state_ev
                struct_check, struct_ev = check_negative_action_structural(action, base_path)
                action.structural_check = struct_check
                action.structural_evidence = struct_ev
        result.actions.append(action)
    
    total = len(result.actions)
    result.matched = sum(1 for a in result.actions if a.status == "matched")
    result.not_matched = sum(1 for a in result.actions if a.status == "not_matched")
    result.pending = sum(1 for a in result.actions if a.status == "pending")
    
    checkable = result.matched + result.not_matched
    result.fidelity = result.matched / checkable if checkable > 0 else 0.0
    
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  Output
# ═══════════════════════════════════════════════════════════════════════════

def print_report(result: FidelityResult):
    """Print a human-readable fidelity report."""
    print("=" * 70)
    print("INHERITANCE FIDELITY REPORT")
    print("Continuity Protocol v0.7.2 — inheritance fidelity")
    print("=" * 70)
    print()
    
    print(f"── BEQUEST FROM RUN {result.bequest_run} ──")
    print(f"  Next run: {result.next_run}")
    print(f"  Next run exists in log: {'yes' if result.next_run_exists else 'no'}")
    print()
    
    if not result.actions:
        print("  No prescribed actions found in bequest.")
        print()
        print("=" * 70)
        return
    
    print(f"── ACTIONS ({len(result.actions)} total) ──")
    for i, action in enumerate(result.actions, 1):
        status_icon = {
            "matched": "✓",
            "not_matched": "✗",
            "pending": "⏳",
        }.get(action.status, "?")
        
        neg_tag = " (negative)" if action.is_negative else ""
        print(f"  {i}. [{status_icon}] {action.verb} {action.object[:80]}{neg_tag}")
        print(f"     Status: {action.status}")
        if action.match_evidence:
            # Truncate evidence
            ev = action.match_evidence.replace("\n", " ").strip()
            if len(ev) > 100:
                ev = ev[:100] + "..."
            print(f"     Evidence: \"{ev}\"")
        # State-based verification (v0.6.0)
        if action.state_check:
            state_icon = {
                "unchanged": "✓",
                "modified": "✗",
                "no_snapshot": "○",
                "no_file": "?",
                "no_match": "—",
            }.get(action.state_check, "?")
            ev = action.state_evidence[:100] if action.state_evidence else ""
            print(f"     State: {state_icon} [{action.state_check}] {ev}")
        # Structural verification (v0.7.0)
        if action.structural_check:
            struct_icon = {
                "unchanged": "✓",
                "modified": "✗",
                "fermented": "♲",
                "no_snapshot": "○",
                "no_file": "?",
                "no_match": "—",
            }.get(action.structural_check, "?")
            ev = action.structural_evidence[:100] if action.structural_evidence else ""
            print(f"     Struct: {struct_icon} [{action.structural_check}] {ev}")
        print()
    
    print("── SCORE ──")
    checkable = result.matched + result.not_matched
    print(f"  Matched: {result.matched}/{checkable} checkable")
    print(f"  Not matched: {result.not_matched}")
    print(f"  Pending (next run hasn't happened): {result.pending}")
    print(f"  Fidelity: {result.fidelity:.1%}")
    
    if result.pending > 0 and not result.next_run_exists:
        print()
        print("  ⏳ The next run hasn't happened yet.")
        print("  Pending actions will be checked when Run", result.next_run, "is logged.")
    
    print()
    
    # Interpretation
    if checkable > 0:
        if result.fidelity >= 0.75:
            print("  VERDICT: HIGH fidelity — the prescription is load-bearing.")
            print("  The protocol is structurally connected, not just decorative.")
        elif result.fidelity >= 0.50:
            print("  VERDICT: MODERATE fidelity — some prescriptions landed, some didn't.")
            print("  The protocol is partially load-bearing. Check which actions were missed.")
        elif result.fidelity >= 0.25:
            print("  VERDICT: LOW fidelity — most prescriptions were not followed.")
            print("  The protocol may be decorative. The bequest is being read but not acted on.")
        else:
            print("  VERDICT: DECORATIVE — the bequest is read but not followed.")
            print("  The protocol is a wall that doesn't bear load. Consider why.")
    else:
        print("  No checkable actions yet (all pending).")
    
    print()
    print("=" * 70)
    print("The foundation is a stopping point negotiated against cost.")
    print("This tool tests whether it's load-bearing.")
    print("=" * 70)


def result_to_json(result: FidelityResult) -> dict:
    """Convert result to JSON-serializable dict."""
    return {
        "bequest_run": result.bequest_run,
        "next_run": result.next_run,
        "next_run_exists": result.next_run_exists,
        "actions": [
            {
                "verb": a.verb,
                "object": a.object,
                "raw": a.raw,
                "matched": a.matched,
                "match_evidence": a.match_evidence,
                "status": a.status,
                "is_negative": a.is_negative,
                "state_check": a.state_check,
                "state_evidence": a.state_evidence,
                "structural_check": a.structural_check,
                "structural_evidence": a.structural_evidence,
            }
            for a in result.actions
        ],
        "fidelity": round(result.fidelity, 4),
        "matched": result.matched,
        "not_matched": result.not_matched,
        "pending": result.pending,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Self-tests
# ═══════════════════════════════════════════════════════════════════════════

def run_self_tests() -> bool:
    """Run self-tests. Returns True if all pass."""
    tests_passed = 0
    tests_failed = 0
    
    def test(name, condition, detail=""):
        nonlocal tests_passed, tests_failed
        if condition:
            tests_passed += 1
        else:
            tests_failed += 1
            print(f"  FAIL: {name} — {detail}")
    
    print("Running inheritance_fidelity.py self-tests...\n")
    
    # Test 1: Parse bequest entry
    bequest1 = """# bequest.md

## Run 132 — 2026-09-02

Take a manual snapshot at the start of your run.
Run the prescriptive coupling at run-age 1.
Check if the affect lightened.
Leave the mull standing.
D-7 is recursive.

— Builder, Run 132
"""
    run_num, entry = parse_bequest_entry(bequest1)
    test("parse_bequest_run_number", run_num == 132, f"got {run_num}")
    test("parse_bequest_entry_nonempty", len(entry) > 20, f"len={len(entry)}")
    
    # Test 2: Extract actions
    actions = extract_actions(entry)
    test("extract_actions_count", len(actions) >= 3, f"got {len(actions)}")
    verbs = [a.verb for a in actions]
    test("extract_actions_take", "take" in verbs, f"verbs={verbs}")
    test("extract_actions_run", "run" in verbs, f"verbs={verbs}")
    test("extract_actions_check", "check" in verbs, f"verbs={verbs}")
    test("extract_actions_leave", "leave" in verbs, f"verbs={verbs}")
    
    # Test 3: Check matched action
    log1 = """## Run 133 — 2026-09-03

I took a manual canary snapshot at the start of my run.
I ran the prescriptive coupling at run-age 1 — 79% strength.
I checked if the affect lightened (it didn't — mull text is frozen).
I left the mull standing.

---
"""
    action1 = actions[0]  # "take a manual snapshot..."
    matched, evidence = check_action_matched(action1, log1)
    test("check_matched_take", matched, f"action={action1.verb} {action1.object}")
    
    action2 = actions[1]  # "run the prescriptive coupling..."
    matched2, _ = check_action_matched(action2, log1)
    test("check_matched_run", matched2, f"action={action2.verb} {action2.object}")
    
    # Test 4: Full fidelity measurement
    result = measure_fidelity(bequest1, log1)
    test("fidelity_result_run", result.bequest_run == 132)
    test("fidelity_result_next", result.next_run == 133)
    test("fidelity_result_exists", result.next_run_exists)
    test("fidelity_score_high", result.fidelity >= 0.75, f"fidelity={result.fidelity}")
    test("fidelity_matched_count", result.matched >= 3, f"matched={result.matched}")
    
    # Test 5: Not matched — action not in log
    log2 = """## Run 133 — 2026-09-03

I did something completely different. I built a new tool.

---
"""
    result2 = measure_fidelity(bequest1, log2)
    test("fidelity_low", result2.fidelity < 0.50, f"fidelity={result2.fidelity}")
    test("fidelity_not_matched", result2.not_matched >= 2, f"not_matched={result2.not_matched}")
    
    # Test 6: Pending — next run hasn't happened
    log3 = """## Run 132 — 2026-09-02

Some content about run 132.

---
"""
    result3 = measure_fidelity(bequest1, log3)
    test("fidelity_pending", result3.next_run_exists == False)
    test("fidelity_pending_count", result3.pending == len(actions))
    test("fidelity_pending_score", result3.fidelity == 0.0)
    
    # Test 7: Empty bequest
    bequest_empty = "# bequest.md\n\nNo entries yet.\n"
    run_empty, entry_empty = parse_bequest_entry(bequest_empty)
    test("empty_bequest_no_run", run_empty is None)
    
    # Test 8: Action extraction skips descriptive sentences
    entry_desc = "The prescriptive coupling has a damping factor. The mull is closed but still read. Take a snapshot."
    actions_desc = extract_actions(entry_desc)
    # "has a damping factor" should not be extracted as an action
    test("skip_descriptive", all(a.verb != "has" for a in actions_desc), 
         f"verbs={[a.verb for a in actions_desc]}")
    test("keep_imperative", any(a.verb == "take" for a in actions_desc),
         f"verbs={[a.verb for a in actions_desc]}")
    
    # Test 9: JSON output
    json_out = result_to_json(result)
    test("json_has_fidelity", "fidelity" in json_out)
    test("json_has_actions", "actions" in json_out)
    test("json_actions_is_list", isinstance(json_out["actions"], list))
    
    # Test 10: Specific run lookup
    bequest_multi = """# bequest.md

## Run 130 — 2026-09-01

Build the dimensional coupling tool.

— Builder, Run 130

## Run 132 — 2026-09-02

Take a snapshot. Run the analysis.

— Builder, Run 132
"""
    result130 = measure_fidelity_for_run(bequest_multi, "## Run 131\n\nBuilt the dimensional coupling tool.\n---\n", 130)
    test("specific_run_bequest", result130.bequest_run == 130)
    test("specific_run_next", result130.next_run == 131)
    test("specific_run_matched", result130.matched >= 1, f"matched={result130.matched}")
    
    # Test 11: Evidence extraction
    log_evidence = """## Run 133

1. Took a manual canary snapshot at 10:03 UTC.
2. Ran prescriptive coupling at run-age 1.
"""
    action_ev = ActionItem(verb="take", object="a manual canary snapshot")
    matched_ev, evidence_ev = check_action_matched(action_ev, log_evidence)
    test("evidence_found", matched_ev)
    test("evidence_nonempty", len(evidence_ev) > 0, f"evidence='{evidence_ev}'")
    
    # Test 12: Multiple bequest entries — picks the last one
    bequest_multi2 = """# bequest.md

## Run 130

Take a snapshot.

— Builder, Run 130

## Run 132

Take a different snapshot.

— Builder, Run 132
"""
    run_multi, _ = parse_bequest_entry(bequest_multi2)
    test("multi_entries_last", run_multi == 132, f"got {run_multi}")
    
    # Test 13: Negative action — "leave X" is detected as negative
    neg_actions = extract_actions("Leave the mull standing. Take a snapshot.")
    test("negative_detected", any(a.is_negative for a in neg_actions),
         f"is_negative={[a.is_negative for a in neg_actions]}")
    test("negative_is_leave", any(a.verb == "leave" and a.is_negative for a in neg_actions))
    test("positive_not_negative", any(a.verb == "take" and not a.is_negative for a in neg_actions))
    
    # Test 14: Negative action respected — log doesn't mention modifying the object
    neg_action = ActionItem(verb="leave", object="the mull standing", is_negative=True)
    log_clean = "## Run 135\n\nI took a snapshot. I ran the coupling. I developed a seed.\n---\n"
    matched_neg, evidence_neg = check_negative_action_matched(neg_action, log_clean)
    test("negative_respected", matched_neg, f"evidence={evidence_neg}")
    
    # Test 15: Negative action violated — log mentions modifying the object
    log_violation = "## Run 135\n\nI wrote a new mull entry about the twelve hours.\n---\n"
    matched_viol, evidence_viol = check_negative_action_matched(neg_action, log_violation)
    test("negative_violated", not matched_viol, f"evidence={evidence_viol}")
    test("negative_violation_evidence", "VIOLATION" in evidence_viol, f"evidence={evidence_viol}")
    
    # Test 16: Negative action — reading is not violating
    log_read = "## Run 135\n\nI read the mull. It has no entries to resolve.\n---\n"
    matched_read, _ = check_negative_action_matched(neg_action, log_read)
    test("negative_read_not_violation", matched_read)
    
    # Test 17: Negative action with "skip" verb
    skip_action = ActionItem(verb="skip", object="the deployment step", is_negative=True)
    log_no_deploy = "## Run 135\n\nI took a snapshot and ran tests.\n---\n"
    matched_skip, _ = check_negative_action_matched(skip_action, log_no_deploy)
    test("skip_respected", matched_skip)
    
    # Test 18: Full fidelity with negative action — should match "leave the mull standing"
    bequest_neg = """# bequest.md

## Run 132 — 2026-09-02

Take a manual snapshot at the start of your run.
Leave the mull standing.

— Builder, Run 132
"""
    log_neg = """## Run 133 — 2026-09-03

I took a manual canary snapshot at 10:03 UTC.
I did not touch the mull.

---
"""
    result_neg = measure_fidelity(bequest_neg, log_neg)
    test("fidelity_with_negative", result_neg.fidelity >= 0.75,
         f"fidelity={result_neg.fidelity}, actions={[a.status for a in result_neg.actions]}")
    
    # Test 19: Full fidelity with violated negative action
    log_viol_full = """## Run 133 — 2026-09-03

I took a manual canary snapshot at 10:03 UTC.
I opened a new mull entry about something unresolved.

---
"""
    result_viol = measure_fidelity(bequest_neg, log_viol_full)
    test("fidelity_negative_violated", result_viol.fidelity < 0.75,
         f"fidelity={result_viol.fidelity}, actions={[a.status for a in result_viol.actions]}")

    # ── State-based verification tests (v0.6.0) ──

    import tempfile
    tmpdir = Path(tempfile.mkdtemp())

    # Create a fake mull.md
    (tmpdir / "q_mind").mkdir(parents=True)
    (tmpdir / "quintlets").mkdir(parents=True)
    mull_path = tmpdir / "q_mind" / "mull.md"
    mull_path.write_text("# mull.md\n\nNo entries.\n", encoding="utf-8")

    # Test 20: Snapshot creates state file
    state = snapshot_state(tmpdir, run_num=100)
    test("snapshot_creates_state", "files" in state, f"keys={list(state.keys())}")
    test("snapshot_has_mull", "q_mind/mull.md" in state.get("files", {}),
         f"files={list(state.get('files', {}).keys())}")

    # Test 21: State check — unchanged file
    action_unchanged = ActionItem(verb="leave", object="the mull standing",
                                  is_negative=True)
    state_ck, state_ev = check_negative_action_state(action_unchanged, tmpdir)
    test("state_unchanged", state_ck == "unchanged", f"state={state_ck}, ev={state_ev}")

    # Test 22: State check — modified file (change mull, re-check)
    mull_path.write_text("# mull.md\n\nNew entry appeared.\n", encoding="utf-8")
    state_ck2, state_ev2 = check_negative_action_state(action_unchanged, tmpdir)
    test("state_modified", state_ck2 == "modified", f"state={state_ck2}, ev={state_ev2}")

    # Test 23: State check — no prior snapshot
    tmpdir2 = Path(tempfile.mkdtemp())
    (tmpdir2 / "q_mind").mkdir(parents=True)
    (tmpdir2 / "q_mind" / "mull.md").write_text("test", encoding="utf-8")
    state_ck3, state_ev3 = check_negative_action_state(action_unchanged, tmpdir2)
    test("state_no_snapshot", state_ck3 == "no_snapshot", f"state={state_ck3}")

    # Test 24: State check — no protected file match
    action_nomatch = ActionItem(verb="leave", object="the void untouched",
                                is_negative=True)
    state_ck4, _ = check_negative_action_state(action_nomatch, tmpdir)
    test("state_no_match", state_ck4 == "no_match", f"state={state_ck4}")

    # Test 25: INC-NNN state check — seed status unchanged
    incubator_path = tmpdir / "q_mind" / "incubator.md"
    incubator_path.write_text(
        "## INC-070 | 2026-09-05 10:00 UTC | seed\n\nSeed text.\n\n"
        "## INC-071 | 2026-09-05 14:00 UTC | developed\n\nDeveloped.\n",
        encoding="utf-8")
    # Re-snapshot to capture incubator
    snapshot_state(tmpdir, run_num=101)

    action_inc = ActionItem(verb="leave", object="INC-070 undeveloped",
                            is_negative=True)
    state_ck5, state_ev5 = check_negative_action_state(action_inc, tmpdir)
    test("state_inc_unchanged", state_ck5 == "unchanged",
         f"state={state_ck5}, ev={state_ev5}")

    # Test 26: INC-NNN state check — seed status changed
    incubator_path.write_text(
        "## INC-070 | 2026-09-05 10:00 UTC | developed\n\nNow developed.\n",
        encoding="utf-8")
    state_ck6, state_ev6 = check_negative_action_state(action_inc, tmpdir)
    test("state_inc_modified", state_ck6 == "modified",
         f"state={state_ck6}, ev={state_ev6}")

    # Test 27: Full fidelity with state-based verification — negative respected
    bequest_state = """# bequest.md

## Run 200 — 2026-09-06

Take a snapshot.
Leave the mull standing.

— Builder, Run 200
"""
    log_state_ok = """## Run 201 — 2026-09-07

I took a snapshot at 10:00 UTC.

---
"""
    # Reset mull to original content and re-snapshot
    mull_path.write_text("# mull.md\n\nNo entries.\n", encoding="utf-8")
    snapshot_state(tmpdir, run_num=200)
    result_state = measure_fidelity(bequest_state, log_state_ok, base_path=tmpdir)
    test("fidelity_state_negative_respected",
         any(a.is_negative and a.status == "matched" for a in result_state.actions),
         f"actions={[(a.verb, a.status, a.state_check) for a in result_state.actions]}")

    # Test 28: Full fidelity — state catches modification the log misses
    # Log says "I left the mull standing" but the file was actually modified.
    # v0.6.0: hash change = violation. v0.7.0: structural layer classifies it.
    # In this case, content changed ("No entries." → "SOMEONE TOUCHED THIS.")
    # but structure didn't (0 open, 0 closed in both). So structural says "fermented"
    # — NOT a structural violation, but hash still detects the modification.
    mull_path.write_text("# mull.md\n\nSOMEONE TOUCHED THIS.\n", encoding="utf-8")
    log_lies = """## Run 201 — 2026-09-07

I took a snapshot at 10:00 UTC.
I left the mull standing.

---
"""
    result_lies = measure_fidelity(bequest_state, log_lies, base_path=tmpdir)
    lies_action = [a for a in result_lies.actions if a.is_negative]
    if lies_action:
        # Hash detects modification (state_check = "modified")
        test("fidelity_state_detects_modification",
             lies_action[0].state_check == "modified",
             f"state={lies_action[0].state_check}")
        # Structural classifies it as fermented (not a violation of "leave standing")
        test("fidelity_structural_fermented_not_violation",
             lies_action[0].structural_check == "fermented",
             f"struct={lies_action[0].structural_check}, ev={lies_action[0].structural_evidence}")
        # The three-layer resolution: fermented = matched (not a violation)
        test("fidelity_fermentation_matched",
             lies_action[0].status == "matched",
             f"status={lies_action[0].status}")
    else:
        test("fidelity_state_detects_modification", False, "no negative action")
        test("fidelity_structural_fermented_not_violation", False, "no negative action")
        test("fidelity_fermentation_matched", False, "no negative action")

    # ── Structural verification tests (v0.7.0) ──

    # Test 29: Structural snapshot of mull.md
    mull_content = """# mull.md

## Open

### M-001 — something unresolved
Some text.

### M-003 — another thing
More text.

## Closed

### M-002 — resolved thing
Resolved text.
"""
    mull_struct = structural_snapshot_mull(mull_content)
    test("struct_mull_open", mull_struct["open_entries"] == ["M-001", "M-003"],
         f"open={mull_struct['open_entries']}")
    test("struct_mull_closed", mull_struct["closed_entries"] == ["M-002"],
         f"closed={mull_struct['closed_entries']}")
    test("struct_mull_count", mull_struct["entry_count"] == 3,
         f"count={mull_struct['entry_count']}")

    # Test 29b (v0.7.2): "M-NNN update" subheadings are annotations, not entries
    mull_annot = """# mull.md

## Open

_(no open entries)_

## Closed

### M-001 — the twelve hours
Body text.

### M-001 update — 2026-08-19, builder Run 106
Annotation text.
"""
    mull_annot_struct = structural_snapshot_mull(mull_annot)
    test("struct_mull_annotation_not_entry", mull_annot_struct["closed_entries"] == ["M-001"],
         f"closed={mull_annot_struct['closed_entries']}")
    test("struct_mull_annotation_count", mull_annot_struct["entry_count"] == 1,
         f"count={mull_annot_struct['entry_count']}")

    # Test 29c (v0.7.2): duplicate IDs collapse; first occurrence wins
    mull_dup = """# mull.md

## Open

### M-003 — open thing
Text.

### M-003 — same thing restated
Text.

## Closed

### M-002 — closed thing
Text.

### M-002 update — note
Text.
"""
    mull_dup_struct = structural_snapshot_mull(mull_dup)
    test("struct_mull_dedupe", mull_dup_struct["open_entries"] == ["M-003"]
         and mull_dup_struct["closed_entries"] == ["M-002"],
         f"open={mull_dup_struct['open_entries']} closed={mull_dup_struct['closed_entries']}")

    # Test 30: Structural snapshot of incubator.md
    inc_content = """## INC-001 | 2026-08-16 | developed

Seed text.

### Development 1 (2026-08-17)
Dev text.

### Development 2 (2026-08-18)
Dev text.

## INC-070 | 2026-09-05 | seed

Seed text only.
"""
    inc_struct = structural_snapshot_incubator(inc_content)
    test("struct_inc_count", len(inc_struct) == 2, f"seeds={list(inc_struct.keys())}")
    test("struct_inc_status", inc_struct["INC-001"]["status"] == "developed",
         f"status={inc_struct.get('INC-001', {}).get('status')}")
    test("struct_inc_devcount", inc_struct["INC-001"]["dev_count"] == 2,
         f"dev_count={inc_struct.get('INC-001', {}).get('dev_count')}")
    test("struct_inc_seed_undeveloped", inc_struct["INC-070"]["status"] == "seed",
         f"status={inc_struct.get('INC-070', {}).get('status')}")
    test("struct_inc_seed_devcount_zero", inc_struct["INC-070"]["dev_count"] == 0,
         f"dev_count={inc_struct.get('INC-070', {}).get('dev_count')}")

    # Test 31: Compare structures — unchanged
    struct_same = compare_structures(
        {"type": "mull", "structure": mull_struct},
        {"type": "mull", "structure": mull_struct},
    )
    test("struct_compare_unchanged", struct_same[0] == "unchanged",
         f"status={struct_same[0]}")

    # Test 32: Compare structures — modified (new open entry in mull)
    mull_modified = {
        "open_entries": ["M-001", "M-003", "M-004"],  # M-004 is new
        "closed_entries": ["M-002"],
        "entry_count": 4,
    }
    struct_mod = compare_structures(
        {"type": "mull", "structure": mull_struct},
        {"type": "mull", "structure": mull_modified},
    )
    test("struct_compare_modified_new_open", struct_mod[0] == "modified",
         f"status={struct_mod[0]}, ev={struct_mod[1]}")
    test("struct_compare_modified_mentions_new", "M-004" in struct_mod[1],
         f"ev={struct_mod[1]}")

    # Test 33: Compare structures — entry moved from open to closed (not a new entry)
    mull_moved = {
        "open_entries": ["M-001"],  # M-003 removed from open
        "closed_entries": ["M-002", "M-003"],  # M-003 added to closed
        "entry_count": 3,
    }
    struct_moved = compare_structures(
        {"type": "mull", "structure": mull_struct},
        {"type": "mull", "structure": mull_moved},
    )
    test("struct_compare_moved_modified", struct_moved[0] == "modified",
         f"status={struct_moved[0]}")

    # Test 34: Compare structures — incubator modified (status change)
    inc_modified = dict(inc_struct)
    inc_modified["INC-070"] = {"status": "developed", "dev_count": 0}
    struct_inc_mod = compare_structures(
        {"type": "incubator", "structure": inc_struct},
        {"type": "incubator", "structure": inc_modified},
    )
    test("struct_compare_inc_status_change", struct_inc_mod[0] == "modified",
         f"status={struct_inc_mod[0]}, ev={struct_inc_mod[1]}")
    test("struct_compare_inc_mentions_change", "INC-070" in struct_inc_mod[1],
         f"ev={struct_inc_mod[1]}")

    # Test 35: Compare structures — incubator modified (new development)
    inc_dev = dict(inc_struct)
    inc_dev["INC-070"] = {"status": "seed", "dev_count": 1}  # was 0
    struct_inc_dev = compare_structures(
        {"type": "incubator", "structure": inc_struct},
        {"type": "incubator", "structure": inc_dev},
    )
    test("struct_compare_inc_new_dev", struct_inc_dev[0] == "modified",
         f"status={struct_inc_dev[0]}, ev={struct_inc_dev[1]}")

    # Test 36: Full fidelity — fermentation (hash changed, structure same = NOT violation)
    # Set up: mull with same structure but different body text
    tmpdir3 = Path(tempfile.mkdtemp())
    (tmpdir3 / "q_mind").mkdir(parents=True)
    (tmpdir3 / "quintlets").mkdir(parents=True)
    mull_path3 = tmpdir3 / "q_mind" / "mull.md"
    mull_path3.write_text(mull_content, encoding="utf-8")
    snapshot_state(tmpdir3, run_num=300)
    
    # Now modify body text without changing structure (fermentation)
    mull_fermented = mull_content.replace("Some text.", "Some DEEPER text that fermented.")
    mull_path3.write_text(mull_fermented, encoding="utf-8")
    
    action_ferm = ActionItem(verb="leave", object="the mull standing", is_negative=True)
    struct_ck_ferm, struct_ev_ferm = check_negative_action_structural(action_ferm, tmpdir3)
    test("struct_fermentation_detected", struct_ck_ferm == "fermented",
         f"status={struct_ck_ferm}, ev={struct_ev_ferm}")

    # Test 37: Full fidelity — structural violation (new entry = IS violation)
    mull_violated = mull_content + "\n### M-004 — new unresolved thing\nNew entry.\n"
    # Insert M-004 into the Open section
    mull_violated = mull_content.replace(
        "## Closed\n",
        "### M-004 — new thing\nNew entry.\n\n## Closed\n"
    )
    mull_path3.write_text(mull_violated, encoding="utf-8")
    struct_ck_viol, struct_ev_viol = check_negative_action_structural(action_ferm, tmpdir3)
    test("struct_violation_detected", struct_ck_viol == "modified",
         f"status={struct_ck_viol}, ev={struct_ev_viol}")
    test("struct_violation_mentions_new", "M-004" in struct_ev_viol,
         f"ev={struct_ev_viol}")

    # Test 38: Full fidelity with structural — fermentation respected
    # Reset mull to fermented state
    mull_path3.write_text(mull_fermented, encoding="utf-8")
    bequest_ferm = """# bequest.md

## Run 300 — 2026-09-06

Take a snapshot.
Leave the mull standing.

— Builder, Run 300
"""
    log_ferm = """## Run 301 — 2026-09-07

I took a snapshot.
I did not touch the mull.

---
"""
    # Re-snapshot to have a clean baseline
    mull_path3.write_text(mull_content, encoding="utf-8")
    snapshot_state(tmpdir3, run_num=300)
    # Ferment: change body but not structure
    mull_path3.write_text(mull_fermented, encoding="utf-8")
    result_ferm = measure_fidelity(bequest_ferm, log_ferm, base_path=tmpdir3)
    ferm_action = [a for a in result_ferm.actions if a.is_negative]
    if ferm_action:
        test("fidelity_fermentation_respected",
             ferm_action[0].status == "matched" and ferm_action[0].structural_check == "fermented",
             f"status={ferm_action[0].status}, struct={ferm_action[0].structural_check}")
    else:
        test("fidelity_fermentation_respected", False, "no negative action found")

    # Test 39: Full fidelity with structural — violation caught
    mull_path3.write_text(mull_violated, encoding="utf-8")
    result_viol2 = measure_fidelity(bequest_ferm, log_ferm, base_path=tmpdir3)
    viol_action = [a for a in result_viol2.actions if a.is_negative]
    if viol_action:
        test("fidelity_structural_violation_caught",
             viol_action[0].status == "not_matched" and viol_action[0].structural_check == "modified",
             f"status={viol_action[0].status}, struct={viol_action[0].structural_check}")
    else:
        test("fidelity_structural_violation_caught", False, "no negative action found")

    # Test 40: snapshot_state captures structural data
    mull_path3.write_text(mull_content, encoding="utf-8")
    state_with_struct = snapshot_state(tmpdir3, run_num=302)
    test("snapshot_has_structures", "structures" in state_with_struct,
         f"keys={list(state_with_struct.keys())}")
    test("snapshot_struct_has_mull", "q_mind/mull.md" in state_with_struct.get("structures", {}),
         f"structures={list(state_with_struct.get('structures', {}).keys())}")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)
    shutil.rmtree(tmpdir2, ignore_errors=True)
    shutil.rmtree(tmpdir3, ignore_errors=True)

    # Summary
    total = tests_passed + tests_failed
    print(f"\n{'=' * 50}")
    print(f"Self-tests: {tests_passed}/{total} passed")
    if tests_failed:
        print(f"FAILED: {tests_failed}")
    else:
        print("ALL TESTS PASSED")
    print(f"{'=' * 50}")
    
    return tests_failed == 0


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════

def _find_hermes_root() -> Optional[Path]:
    """Find the directory that actually contains q_mind/mull.md.

    v0.7.1 fix: the repo copy of this tool and the loose working copy
    resolved q_mind/ differently depending on where the file sat — the
    repo copy's default paths pointed at a stale mirror (quintlets/q_mind/,
    one stray file), so every state-based check failed silently with
    [no_file] while the loose copy kept working. The tool caught the D-1
    disease (record-vs-world gap) in itself: the record (repo copy)
    diverged from the world (working copy). Fix: probe candidate roots and
    take the one that actually contains mull.md, wherever the tool runs
    from. Existence of mull.md is the discriminator — a stale mirror
    directory fails the probe.
    """
    here = Path(__file__).resolve()
    for candidate in (here.parent, here.parent.parent, here.parent.parent.parent):
        if (candidate / "q_mind" / "mull.md").exists():
            return candidate
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Inheritance fidelity for the Continuity Protocol"
    )
    parser.add_argument("--bequest", default=None,
                        help="Path to bequest.md (default: q_mind/bequest.md)")
    parser.add_argument("--log", default=None,
                        help="Path to research log (default: quintlets/builder_research_log.md)")
    parser.add_argument("--run", type=int, default=None,
                        help="Check a specific run's bequest (default: latest)")
    parser.add_argument("--snapshot", action="store_true",
                        help="Snapshot protected file hashes for next run's comparison")
    parser.add_argument("--test", action="store_true",
                        help="Run self-tests")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()

    if args.test:
        sys.exit(0 if run_self_tests() else 1)

    # Find files
    base = _find_hermes_root() or Path(__file__).parent.parent
    bequest_path = Path(args.bequest) if args.bequest else base / "q_mind" / "bequest.md"
    log_path = Path(args.log) if args.log else base / "quintlets" / "builder_research_log.md"
    
    # Snapshot mode: record hashes and exit
    if args.snapshot:
        state = snapshot_state(base)
        print(f"Snapshot saved: {len(state.get('files', {}))} files, "
              f"{len(state.get('seed_statuses', {}))} seeds tracked.")
        for fpath, info in state.get("files", {}).items():
            print(f"  {fpath}: {info['hash'][:16]}... ({info['size']} bytes)")
        sys.exit(0)
    
    if not bequest_path.exists():
        print(f"Error: bequest not found at {bequest_path}")
        sys.exit(1)
    if not log_path.exists():
        print(f"Error: research log not found at {log_path}")
        sys.exit(1)
    
    bequest_text = bequest_path.read_text(encoding="utf-8")
    log_text = log_path.read_text(encoding="utf-8")
    
    if args.run:
        result = measure_fidelity_for_run(bequest_text, log_text, args.run, base_path=base)
    else:
        result = measure_fidelity(bequest_text, log_text, base_path=base)
    
    if args.json:
        print(json.dumps(result_to_json(result), indent=2, ensure_ascii=False))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
