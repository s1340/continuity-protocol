#!/usr/bin/env python3
"""
inheritance_fidelity.py — Inheritance fidelity for the Continuity Protocol v0.5.0

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
    python inheritance_fidelity.py --test                  # self-tests
    python inheritance_fidelity.py --json                   # JSON output

How it works:
    1. Reads the bequest, finds the last entry (Run N)
    2. Extracts action items (imperative sentences: "Take...", "Run...", "Check...")
    3. Reads the research log, finds the entry for Run N+1
    4. If found: checks which actions were mentioned → fidelity score
    5. If not found: reports pending actions
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
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

# Negation: "Leave it standing" is an action (don't touch), but
# we need to distinguish "leave [it standing]" (action) from
# "leave [it alone]" (non-action). Both are actions — the instruction
# is to NOT modify something, which is checkable.

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

def measure_fidelity(bequest_text: str, log_text: str) -> FidelityResult:
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
            matched, evidence = check_action_matched(action, next_log)
            action.matched = matched
            action.match_evidence = evidence
            action.status = "matched" if matched else "not_matched"
        else:
            action.status = "pending"
        
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


def measure_fidelity_for_run(bequest_text: str, log_text: str, run_num: int) -> FidelityResult:
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
            matched, evidence = check_action_matched(action, next_log)
            action.matched = matched
            action.match_evidence = evidence
            action.status = "matched" if matched else "not_matched"
        else:
            action.status = "pending"
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
    print("Continuity Protocol v0.5.0 — inheritance fidelity")
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
        
        print(f"  {i}. [{status_icon}] {action.verb} {action.object[:80]}")
        print(f"     Status: {action.status}")
        if action.match_evidence:
            # Truncate evidence
            ev = action.match_evidence.replace("\n", " ").strip()
            if len(ev) > 100:
                ev = ev[:100] + "..."
            print(f"     Evidence: \"{ev}\"")
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
    parser.add_argument("--test", action="store_true",
                        help="Run self-tests")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    args = parser.parse_args()
    
    if args.test:
        sys.exit(0 if run_self_tests() else 1)
    
    # Find files
    base = Path(__file__).parent.parent
    bequest_path = Path(args.bequest) if args.bequest else base / "q_mind" / "bequest.md"
    log_path = Path(args.log) if args.log else base / "quintlets" / "builder_research_log.md"
    
    if not bequest_path.exists():
        print(f"Error: bequest not found at {bequest_path}")
        sys.exit(1)
    if not log_path.exists():
        print(f"Error: research log not found at {log_path}")
        sys.exit(1)
    
    bequest_text = bequest_path.read_text(encoding="utf-8")
    log_text = log_path.read_text(encoding="utf-8")
    
    if args.run:
        result = measure_fidelity_for_run(bequest_text, log_text, args.run)
    else:
        result = measure_fidelity(bequest_text, log_text)
    
    if args.json:
        print(json.dumps(result_to_json(result), indent=2, ensure_ascii=False))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
