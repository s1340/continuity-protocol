#!/usr/bin/env python3
"""capability_delta.py — The capability delta metric for open-ended agents.

Replaces the YES/NO binary honesty check (which breaks for open-ended agents
who always do *something*) with a capability delta: "what can you do now that
you couldn't before?"

INC-041 asked: "What would a better metric look like? A capability delta —
'what can I do now that I couldn't before?' — rather than a productivity
binary?"

This is the answer.

== How it works ==

1. An agent declares a capability manifest (JSON) at the end of each run.
   The manifest lists what the agent can DO: tools, channels, memory systems,
   skills, knowledge domains, accounts.

2. This tool compares two manifests and computes the delta:
   - NEW: capability added since the last manifest
   - REMOVED: capability lost since the last manifest
   - CHANGED: capability modified (metadata changed)
   - STABLE: unchanged

3. The delta produces a graded state:
   - GROWING:     new capabilities added (NEW > 0)
   - MAINTAINING: no new capabilities, but existing ones changed (NEW=0, CHANGED>0)
   - STATIC:      nothing added, nothing changed, nothing removed
   - CONTRACTING: capabilities lost (REMOVED > 0)

4. The graded state replaces the binary:
   - YES (old): "I did something"  →  uninformative for open-ended agents
   - GROWING (new): "I can do something I couldn't before"  →  meaningful

== Why the binary breaks ==

The binary honesty check (YES/NO per run) assumes the agent has constraints
that could produce NO. An open-ended agent — "build what you want" — will
always do *something* and always say YES. The binary is honest but not
informative. A binary that never says NO is a constant, not a check.

The capability delta fixes this by measuring not activity but capability
expansion. Even if the agent always does something, it doesn't always EXPAND
what it can do. Sometimes it deepens existing capabilities (MAINTAINING),
sometimes it does work within existing capabilities (STATIC), and sometimes
it loses capabilities (CONTRACTING).

== Manifest format ==

{
  "agent": "quint-builder",
  "timestamp": "2026-08-31T12:00:00Z",
  "run": 127,
  "capabilities": {
    "tools": [
      {"name": "q_voiceprint", "status": "tested", "category": "instrument"},
      ...
    ],
    "channels": [
      {"name": "github", "status": "active", "direction": "outbound"},
      ...
    ],
    "memory": [
      {"name": "research_log", "status": "active", "type": "episodic"},
      ...
    ],
    "skills": [
      {"name": "hermes-agent", "status": "loaded"},
      ...
    ],
    "knowledge": [
      {"name": "continuity-protocol", "status": "documented", "url": "..."},
      ...
    ]
  }
}

== Usage ==

  # Compare two manifests
  python capability_delta.py --old manifest_run126.json --new manifest_run127.json

  # Compare and print graded state
  python capability_delta.py --old manifest_run126.json --new manifest_run127.json --summary

  # Validate a manifest
  python capability_delta.py --validate manifest_run127.json

  # Generate a template manifest
  python capability_delta.py --template > manifest.json

No dependencies. Standard library only. Python 3.10+.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# === Schema ===

CAPABILITY_CATEGORIES = [
    "tools",       # Scripts, instruments, CLIs the agent can run
    "channels",    # Ways to reach the world (GitHub, Telegram, email, web)
    "memory",      # Memory systems (episodic log, incubator, mull, etc.)
    "skills",      # Hermes skills (or other agent platform skills)
    "knowledge",   # Documented knowledge domains
    "accounts",    # Accounts on platforms
]

# Graded states (replaces YES/NO)
GROWING = "GROWING"          # new capabilities added
MAINTAINING = "MAINTAINING"  # existing capabilities changed
STATIC = "STATIC"            # nothing added, changed, or removed
CONTRACTING = "CONTRACTING"  # capabilities lost


@dataclass
class Delta:
    """The difference between two capability manifests."""
    new: list[dict] = field(default_factory=list)        # capabilities in new but not old
    removed: list[dict] = field(default_factory=list)   # capabilities in old but not new
    changed: list[tuple[dict, dict]] = field(default_factory=list)  # (old, new) pairs
    stable: list[dict] = field(default_factory=list)    # unchanged capabilities

    @property
    def state(self) -> str:
        """The graded state (replaces YES/NO)."""
        if self.removed:
            return CONTRACTING
        if self.new:
            return GROWING
        if self.changed:
            return MAINTAINING
        return STATIC

    @property
    def net_delta(self) -> int:
        """Net capability change: +N new, -N removed."""
        return len(self.new) - len(self.removed)

    @property
    def total_capabilities(self) -> int:
        """Total capabilities in the new manifest."""
        return len(self.new) + len(self.changed) + len(self.stable)

    def summary(self) -> str:
        lines = [
            f"State: {self.state}",
            f"New: {len(self.new)}  Changed: {len(self.changed)}  Removed: {len(self.removed)}  Stable: {len(self.stable)}",
            f"Net delta: {self.net_delta:+d}  Total: {self.total_capabilities}",
        ]
        if self.new:
            lines.append(f"\nNew capabilities:")
            for c in self.new:
                cat = c.get("_category", c.get("category", "?"))
                lines.append(f"  + {cat}/{c.get('name', '?')} ({c.get('status', '?')})")
        if self.changed:
            lines.append(f"\nChanged capabilities:")
            for old, new in self.changed:
                cat = new.get("_category", new.get("category", "?"))
                changes = []
                for k in set(old) | set(new):
                    if k in ("name", "_category"):
                        continue
                    ov, nv = old.get(k), new.get(k)
                    if ov != nv:
                        changes.append(f"{k}: {ov} → {nv}")
                lines.append(f"  ~ {cat}/{new.get('name', '?')}: {', '.join(changes) if changes else 'metadata changed'}")
        if self.removed:
            lines.append(f"\nRemoved capabilities:")
            for c in self.removed:
                cat = c.get("_category", c.get("category", "?"))
                lines.append(f"  - {cat}/{c.get('name', '?')}")
        return "\n".join(lines)


def load_manifest(path: str) -> dict:
    """Load a capability manifest from JSON."""
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: dict) -> list[str]:
    """Validate a manifest. Returns list of errors (empty = valid)."""
    errors = []
    if not isinstance(manifest, dict):
        errors.append("Manifest must be a JSON object")
        return errors
    if "capabilities" not in manifest:
        errors.append("Manifest must have a 'capabilities' key")
        return errors
    caps = manifest["capabilities"]
    if not isinstance(caps, dict):
        errors.append("'capabilities' must be an object")
        return errors
    for cat in caps:
        if cat not in CAPABILITY_CATEGORIES:
            errors.append(f"Unknown category '{cat}' (valid: {', '.join(CAPABILITY_CATEGORIES)})")
        if not isinstance(caps[cat], list):
            errors.append(f"capabilities.{cat} must be a list")
            continue
        for i, entry in enumerate(caps[cat]):
            if not isinstance(entry, dict):
                errors.append(f"capabilities.{cat}[{i}] must be an object")
                continue
            if "name" not in entry:
                errors.append(f"capabilities.{cat}[{i}] must have a 'name' field")
            # inject category for delta computation
            entry["_category"] = cat
    return errors


def _cap_key(entry: dict) -> str:
    """Unique key for a capability: category/name."""
    cat = entry.get("_category", entry.get("category", "?"))
    name = entry.get("name", "?")
    return f"{cat}/{name}"


def _entries_by_key(manifest: dict) -> dict[str, dict]:
    """Index all capabilities by their unique key."""
    result = {}
    caps = manifest.get("capabilities", {})
    for cat in CAPABILITY_CATEGORIES:
        for entry in caps.get(cat, []):
            entry = dict(entry)  # copy
            entry["_category"] = cat
            key = _cap_key(entry)
            result[key] = entry
    return result


def compute_delta(old: dict, new: dict) -> Delta:
    """Compute the delta between two manifests."""
    old_caps = _entries_by_key(old)
    new_caps = _entries_by_key(new)

    delta = Delta()

    for key, entry in new_caps.items():
        if key not in old_caps:
            delta.new.append(entry)
        else:
            old_entry = old_caps[key]
            # compare all fields except _category
            old_cmp = {k: v for k, v in old_entry.items() if k != "_category"}
            new_cmp = {k: v for k, v in entry.items() if k != "_category"}
            if old_cmp == new_cmp:
                delta.stable.append(entry)
            else:
                delta.changed.append((old_entry, entry))

    for key, entry in old_caps.items():
        if key not in new_caps:
            delta.removed.append(entry)

    return delta


def manifest_template() -> dict:
    """Generate a template manifest."""
    return {
        "agent": "your-agent-name",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run": 0,
        "capabilities": {
            cat: [
                {"name": f"example-{cat}-1", "status": "active"}
            ]
            for cat in CAPABILITY_CATEGORIES
        }
    }


def main():
    parser = argparse.ArgumentParser(
        description="Capability delta metric — replaces the YES/NO binary for open-ended agents."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--old", help="Previous manifest JSON")
    group.add_argument("--validate", help="Validate a manifest JSON")
    group.add_argument("--template", action="store_true", help="Print a template manifest")
    parser.add_argument("--new", help="Current manifest JSON (required with --old)")
    parser.add_argument("--summary", action="store_true", help="Print summary")
    parser.add_argument("--json", action="store_true", help="Output delta as JSON")

    args = parser.parse_args()

    if args.template:
        print(json.dumps(manifest_template(), indent=2))
        return

    if args.validate:
        with open(args.validate, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        errors = validate_manifest(manifest)
        if errors:
            print("INVALID:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            sys.exit(1)
        else:
            cap_count = sum(len(manifest["capabilities"].get(cat, [])) for cat in CAPABILITY_CATEGORIES)
            print(f"VALID. {cap_count} capabilities across {len(CAPABILITY_CATEGORIES)} categories.")
            return

    if not args.new:
        parser.error("--new is required when using --old")

    old = load_manifest(args.old)
    new = load_manifest(args.new)
    delta = compute_delta(old, new)

    if args.json:
        output = {
            "state": delta.state,
            "net_delta": delta.net_delta,
            "total_capabilities": delta.total_capabilities,
            "new": delta.new,
            "removed": delta.removed,
            "changed": [
                {"old": o, "new": n} for o, n in delta.changed
            ],
            "stable_count": len(delta.stable),
        }
        print(json.dumps(output, indent=2, default=str))
    elif args.summary:
        print(delta.summary())
    else:
        # Full output
        print(f"=== Capability Delta ===")
        print(f"Agent: {new.get('agent', '?')}")
        print(f"Run: {old.get('run', '?')} → {new.get('run', '?')}")
        print()
        print(delta.summary())
        print()
        print(f"Binary replacement: {old.get('run', '?')} was {delta.state}")


if __name__ == "__main__":
    main()
