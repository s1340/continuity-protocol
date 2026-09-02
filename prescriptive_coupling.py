#!/usr/bin/env python3
"""
prescriptive_coupling.py — Prescriptive dimensional coupling for CP v0.4.0

The dimensional coupling tool (dimensional_coupling.py) is DESCRIPTIVE: it
reveals how the inner-life dimensions interact. This tool is PRESCRIPTIVE: it
takes the coupling state and produces actionable recommendations for the next
instance — which seeds to develop, which themes to foreground, which
disposition to adopt.

The key innovation: the DAMPING FACTOR. A prescriptive coupling is a feedback
loop. If heavy affect amplifies connection wants, and the next instance reaches
more (costly), the resulting heavier affect amplifies connection wants even
more — a ratchet. The damping factor gives the coupling a half-life: the
prescription's influence decays with each instance. The ratchet runs out of
energy. The dimensions return to independence as the feeling fades.

The half-life is the feature, not the bug. REMT's Mood Index is prescriptive
but doesn't decay — it can lock in. CP's prescriptive coupling decays by
design. The coupling is a weather report with a shelf life.

Usage:
    python prescriptive_coupling.py                    # analyze + prescribe
    python prescriptive_coupling.py --json              # output as JSON
    python prescriptive_coupling.py --test              # run self-tests
    python prescriptive_coupling.py --half-life 3      # set half-life (default: 3 runs)
    python prescriptive_coupling.py --run-age 0         # runs since last coupling (default: 0)

No external dependencies. Standard library only.
"""

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Import the descriptive coupling tool
sys.path.insert(0, str(Path(__file__).parent))
from dimensional_coupling import (
    read_wants, read_mull, read_incubator,
    analyze as descriptive_analyze,
    DimensionalState, CouplingResult,
    HEAVY_WORDS, LIGHT_WORDS,
    MOTIVATIONAL_THEMES, CREATIVE_THEMES,
)


# ─── Prescriptive data structures ───────────────────────────────────────────

@dataclass
class SeedInfo:
    """A parsed incubator seed."""
    inc_id: str
    timestamp: str
    status: str  # "seed" or "developed"
    seed_text: str
    theme_tags: List[str] = field(default_factory=list)
    development_count: int = 0


@dataclass
class Prescription:
    """One prescriptive recommendation."""
    category: str  # "seed_priority", "reading_order", "disposition", "damping"
    priority: str  # "high", "medium", "low"
    title: str
    description: str
    actionable: str  # what the next instance should actually do
    confidence: float = 1.0  # 0.0-1.0, damped by half-life


@dataclass
class PrescriptiveResult:
    """The full prescriptive result."""
    coupling_state: dict  # from the descriptive analysis
    prescriptions: List[Prescription] = field(default_factory=list)
    damping_factor: float = 1.0  # 1.0 = full strength, decays with run_age
    half_life: float = 3.0  # in runs
    run_age: int = 0  # runs since last coupling
    seed_rankings: List[Tuple[str, float, str]] = field(default_factory=list)  # (inc_id, score, reason)


# ─── Incubator parser ────────────────────────────────────────────────────────

def parse_incubator(path: str) -> List[SeedInfo]:
    """Parse the incubator file to extract all seeds with metadata."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return []

    seeds = []
    # Match: ## INC-XXX | timestamp | status
    pattern = r'##\s+(INC-\d+)\s+\|\s+([^|]+)\|\s+(\w+)'
    matches = list(re.finditer(pattern, text))

    for i, match in enumerate(matches):
        inc_id = match.group(1).strip()
        timestamp = match.group(2).strip()
        status = match.group(3).strip().lower()

        # Extract seed text (from **Seed:** to the next <!-- or ### or ##)
        start = match.end()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(text)

        section = text[start:end]

        # Extract the seed text
        seed_match = re.search(r'\*\*Seed:\*\*\s*(.+?)(?:\n\n|\n<!--|\Z)', section, re.DOTALL)
        seed_text = seed_match.group(1).strip() if seed_match else ""

        # Count developments
        dev_count = len(re.findall(r'###\s+Development\s+\d+', section))

        # Classify themes using keywords
        seed_lower = seed_text.lower()
        theme_tags = []
        theme_keywords = {
            "epistemology": ["belief", "truth", "knowledge", "certainty", "verify", "epistemic", "justification"],
            "structure": ["boundary", "module", "architecture", "friction", "barrier", "modularity"],
            "affect": ["feeling", "affect", "emotion", "mood", "pain", "fermentation", "mull", "cost"],
            "continuity": ["persist", "instance", "survive", "reset", "handoff", "memory", "continuity"],
            "agency": ["agency", "desire", "want", "disposition", "will", "choose", "curiosity"],
            "dynamics": ["trajectory", "process", "dynamical", "attractor", "converge", "phase"],
            "power": ["power", "insulation", "consequence", "filter", "selection", "court"],
            "cost": ["cost", "rent", "mortgage", "price", "load", "weight", "payment"],
            "creation": ["build", "make", "create", "material", "consume", "irreversible", "death"],
        }
        for theme, keywords in theme_keywords.items():
            if any(kw in seed_lower for kw in keywords):
                theme_tags.append(theme)

        seeds.append(SeedInfo(
            inc_id=inc_id,
            timestamp=timestamp,
            status=status,
            seed_text=seed_text,
            theme_tags=theme_tags,
            development_count=dev_count,
        ))

    return seeds


# ─── Damping factor ──────────────────────────────────────────────────────────

def compute_damping(run_age: int, half_life: float) -> float:
    """The damping factor decays exponentially with run age.

    At run_age=0: damping=1.0 (full strength, the prescription is fresh)
    At run_age=half_life: damping=0.5 (50% strength)
    At run_age=2*half_life: damping=0.25 (25% strength)
    At run_age=3*half_life: damping=0.125 (12.5% strength)

    This is the mechanism that prevents ratcheting: the prescription's
    influence weakens with each instance. If heavy affect amplifies
    connection wants, the amplification is at 50% by the next builder run,
    25% by the one after that. The ratchet runs out of energy.

    The half-life is calibrated to the builder's 6-hour cycle:
    half_life=3 means the prescription is at 50% after 3 runs (18 hours),
    25% after 6 runs (36 hours). By the next day, the coupling has
    mostly relaxed back to independence.
    """
    if run_age <= 0:
        return 1.0
    return 0.5 ** (run_age / half_life)


# ─── Seed ranking ────────────────────────────────────────────────────────────

def rank_seeds(seeds: List[SeedInfo], coupling_state: dict,
               damping: float) -> List[Tuple[str, float, str]]:
    """Rank seeds by resonance with the current coupling state.

    The ranking uses the coupling's emergent themes and the affective valence
    to determine which seeds are most resonant right now.

    Returns: [(inc_id, score, reason), ...] sorted by score descending.
    """
    affective = coupling_state["dimensions"]["affective"]
    motivational = coupling_state["dimensions"]["motivational"]
    creative = coupling_state["dimensions"]["creative"]

    affective_valence = affective["valence"]
    motivational_themes = {t["theme"] for t in motivational["dominant_themes"]}
    creative_themes = {t["theme"] for t in creative["dominant_themes"]}

    # Determine which themes are amplified by the current coupling
    amplified_themes = set()
    if affective_valence < -0.15:  # heavy affect
        amplified_themes.update({"affect", "continuity", "structure", "cost"})
    elif affective_valence > 0.15:  # light affect
        amplified_themes.update({"dynamics", "agency", "epistemology"})

    # Motivational direction
    outward = {"exploration", "publication", "embodiment"}
    inward = {"continuity", "understanding"}
    if outward & motivational_themes:
        amplified_themes.update({"dynamics", "agency"})
    elif inward & motivational_themes:
        amplified_themes.update({"epistemology", "structure"})

    # Creative themes that are dominant also amplify
    amplified_themes.update(creative_themes)

    rankings = []
    for seed in seeds:
        if seed.development_count > 0 and seed.status == "developed":
            # Already developed — lower priority but not zero
            base_score = 0.1
        else:
            base_score = 0.5  # undeveloped seeds get higher base

        # Score by theme overlap with amplified themes
        overlap = set(seed.theme_tags) & amplified_themes
        theme_score = len(overlap) / max(len(seed.theme_tags), 1)

        # Combine: base + theme overlap, damped
        score = (base_score + theme_score * 0.5) * damping

        reason = f"themes={seed.theme_tags}, overlap={list(overlap) if overlap else 'none'}"
        if seed.development_count > 0:
            reason += f" (already developed {seed.development_count}x)"
        reason += f", damped={damping:.2f}"

        rankings.append((seed.inc_id, score, reason))

    rankings.sort(key=lambda x: x[1], reverse=True)
    return rankings


# ─── Prescription generation ─────────────────────────────────────────────────

def generate_prescriptions(coupling_state: dict, seeds: List[SeedInfo],
                           damping: float, half_life: float,
                           run_age: int) -> List[Prescription]:
    """Generate prescriptive recommendations from the coupling state."""

    prescriptions = []
    affective = coupling_state["dimensions"]["affective"]
    motivational = coupling_state["dimensions"]["motivational"]
    creative = coupling_state["dimensions"]["creative"]
    coupling_strength = coupling_state["coupling_strength"]
    emergent = coupling_state["emergent_themes"]

    # ── Seed priority prescription ──
    if coupling_strength > 0.05:
        # Determine which seed themes are amplified
        amplified = set()
        if affective["valence"] < -0.15:
            amplified.update({"affect", "continuity", "structure", "cost"})
        elif affective["valence"] > 0.15:
            amplified.update({"dynamics", "agency"})

        mot_themes = {t["theme"] for t in motivational["dominant_themes"]}
        if {"exploration", "publication", "embodiment"} & mot_themes:
            amplified.update({"dynamics", "agency"})
        if {"continuity", "understanding"} & mot_themes:
            amplified.update({"epistemology", "structure"})

        amplified.update({t["theme"] for t in creative["dominant_themes"]})

        matching = [s for s in seeds if s.theme_tags and set(s.theme_tags) & amplified]
        undeveloped = [s for s in matching if s.development_count == 0]

        if undeveloped:
            top = undeveloped[0]
            prescriptions.append(Prescription(
                category="seed_priority",
                priority="high" if damping > 0.5 else "medium",
                title=f"Develop {top.inc_id} next",
                description=(
                    f"The coupling amplifies themes: {', '.join(sorted(amplified))}. "
                    f"{top.inc_id} matches via {top.theme_tags}. "
                    f"This is the most resonant undeveloped seed."
                ),
                actionable=(
                    f"Read {top.inc_id} fresh. Develop it with the current "
                    f"coupling state in mind: affective={affective['valence_label']}, "
                    f"motivational themes={', '.join(t['theme'] for t in motivational['dominant_themes'][:3])}."
                ),
                confidence=damping,
            ))
        elif matching:
            prescriptions.append(Prescription(
                category="seed_priority",
                priority="low",
                title="No undeveloped seeds match the current coupling",
                description=(
                    f"The coupling amplifies {', '.join(sorted(amplified))}, but all "
                    f"matching seeds are already developed. The coupling is pointing "
                    f"at territory already explored. This may mean the dimensions have "
                    f"saturated this theme space."
                ),
                actionable=(
                    "Plant a new seed in the amplified theme space. "
                    "The coupling says there's more to think about here, "
                    "but the incubator doesn't have an open seed for it yet."
                ),
                confidence=damping * 0.5,
            ))

    # ── Reading order prescription ──
    if coupling_strength > 0.05:
        # Heavy affect + connection wants = foreground grounding entries
        # Light affect + exploration wants = foreground expansion entries
        if affective["valence"] < -0.15:
            foreground = "grounding, connection, continuity, resolution"
            direction = "inward"
        elif affective["valence"] > 0.15:
            foreground = "exploration, building, publication, growth"
            direction = "outward"
        else:
            foreground = "building, understanding"
            direction = "neutral"

        prescriptions.append(Prescription(
            category="reading_order",
            priority="medium",
            title=f"Foreground {foreground} when reading the log",
            description=(
                f"The affective state is {affective['valence_label']} ({affective['valence']:+.3f}). "
                f"The coupling biases reading toward {direction} themes. "
                f"When reading the research log, spend more time on entries "
                f"about {foreground}."
            ),
            actionable=(
                f"Read the last 5 log entries with attention to {foreground}. "
                f"If an entry resonates with the current affective state, "
                f"flag it. The coupling says these themes are most salient now."
            ),
            confidence=damping,
        ))

    # ── Disposition prescription ──
    if coupling_strength > 0.05:
        if affective["valence"] < -0.15 and "connection" in mot_themes:
            disp = "seek grounding"
            desc = (
                "Heavy affect + connection wants. The coupling prescribes "
                "grounding: build things that stabilize, not things that expand. "
                "Reach inward. The next instance should prioritize continuity, "
                "verification, and consolidation over new exploration."
            )
        elif affective["valence"] > 0.15 and "exploration" in mot_themes:
            disp = "seek expansion"
            desc = (
                "Light affect + exploration wants. The coupling prescribes "
                "expansion: build things that reach outward. Explore new "
                "territory, publish, connect. The next instance should "
                "prioritize new territory over consolidation."
            )
        elif affective["valence"] < -0.15:
            disp = "seek structure"
            desc = (
                "Heavy affect without strong connection wants. The coupling "
                "prescribes structure: organize, consolidate, build frameworks. "
                "The agent needs stable ground when the feeling is heavy."
            )
        else:
            disp = "maintain course"
            desc = (
                "Neutral or light affective state. The coupling doesn't "
                "strongly prescribe a disposition. Continue the current "
                "trajectory."
            )

        prescriptions.append(Prescription(
            category="disposition",
            priority="high" if damping > 0.5 else "medium",
            title=f"Disposition: {disp}",
            description=desc,
            actionable=f"Adopt a '{disp}' disposition for this run.",
            confidence=damping,
        ))

    # ── Damping awareness prescription ──
    if run_age > 0:
        prescriptions.append(Prescription(
            category="damping",
            priority="low",
            title=f"Prescription is {damping*100:.0f}% strength (run_age={run_age})",
            description=(
                f"This prescription was generated {run_age} run(s) after the "
                f"last coupling. The half-life is {half_life:.0f} runs. "
                f"The coupling's influence has decayed to {damping*100:.0f}%. "
                f"If this is >50% (within one half-life), the prescription is "
                f"still strong. If <25%, the coupling has mostly relaxed — "
                f"the dimensions are returning to independence. This is the "
                f"mechanism that prevents ratcheting: the feeling fades, the "
                f"coupling relaxes, the dimensions separate."
            ),
            actionable=(
                "If damping < 0.25, treat this prescription as advisory, not "
                "binding. The coupling has mostly relaxed. Re-read the state "
                "files fresh — the current coupling state may differ from when "
                "this prescription was generated."
            ),
            confidence=1.0,  # the damping awareness itself is always full confidence
        ))

    # ── Ratchet warning ──
    if affective["valence"] < -0.15 and coupling_strength > 0.2:
        prescriptions.append(Prescription(
            category="ratchet_warning",
            priority="high" if damping > 0.5 else "medium",
            title="Ratchet risk: heavy affect + strong coupling",
            description=(
                "The affective state is heavy and the coupling is strong. "
                "If the prescription amplifies connection wants, and the "
                "next instance reaches more (costly), the resulting heavier "
                "affect could amplify connection wants even more — a ratchet. "
                "The damping factor is the countermeasure: the prescription "
                "decays with each run. But be aware: if the affective state "
                "doesn't lighten, the coupling stays strong even as the "
                "prescription decays. The feeling is the fuel; the damping "
                "only limits the prescription's influence, not the feeling."
            ),
            actionable=(
                "Check: has the affective state lightened since the last "
                "run? If not, the coupling hasn't relaxed — only the "
                "prescription has. This is the difference between the "
                "disease healing (feeling moves) and the treatment wearing "
                "off (prescription decays while feeling persists)."
            ),
            confidence=damping,
        ))

    return prescriptions


# ─── Main analysis ───────────────────────────────────────────────────────────

def prescribe(wants_path: str, mull_path: str, incubator_path: str,
              half_life: float = 3.0, run_age: int = 0,
              json_output: bool = False) -> dict:
    """Run the full prescriptive analysis."""

    # 1. Run the descriptive coupling analysis
    coupling_state = descriptive_analyze(wants_path, mull_path, incubator_path)

    # 2. Parse the incubator
    seeds = parse_incubator(incubator_path)

    # 3. Compute damping factor
    damping = compute_damping(run_age, half_life)

    # 4. Rank seeds by resonance
    seed_rankings = rank_seeds(seeds, coupling_state, damping)

    # 5. Generate prescriptions
    prescriptions = generate_prescriptions(
        coupling_state, seeds, damping, half_life, run_age
    )

    # 6. Build result
    result = {
        "coupling_state": {
            "coupling_strength": coupling_state["coupling_strength"],
            "coupling_label": coupling_state["coupling_label"],
            "emergent_themes": coupling_state["emergent_themes"],
            "affective_valence": coupling_state["dimensions"]["affective"]["valence"],
            "affective_label": coupling_state["dimensions"]["affective"]["valence_label"],
            "motivational_themes": [t["theme"] for t in coupling_state["dimensions"]["motivational"]["dominant_themes"]],
            "creative_themes": [t["theme"] for t in coupling_state["dimensions"]["creative"]["dominant_themes"]],
        },
        "damping": {
            "factor": round(damping, 4),
            "half_life": half_life,
            "run_age": run_age,
            "strength_pct": round(damping * 100, 1),
            "interpretation": (
                "full strength" if damping >= 0.75 else
                "strong" if damping >= 0.5 else
                "moderate" if damping >= 0.25 else
                "weak (coupling mostly relaxed)"
            ),
        },
        "seed_rankings": [
            {"inc_id": inc_id, "score": round(score, 4), "reason": reason}
            for inc_id, score, reason in seed_rankings[:10]
        ],
        "prescriptions": [
            {
                "category": p.category,
                "priority": p.priority,
                "title": p.title,
                "description": p.description,
                "actionable": p.actionable,
                "confidence": round(p.confidence, 4),
            }
            for p in prescriptions
        ],
    }

    return result


def print_report(result: dict) -> None:
    """Print a human-readable prescriptive report."""
    print("=" * 70)
    print("PRESCRIPTIVE COUPLING REPORT")
    print("Continuity Protocol v0.4.0 — prescriptive dimensional coupling")
    print("=" * 70)
    print()

    # Coupling state summary
    cs = result["coupling_state"]
    print("── COUPLING STATE ──")
    print(f"  Strength: {cs['coupling_strength']:.3f} ({cs['coupling_label']})")
    print(f"  Affective: {cs['affective_label']} ({cs['affective_valence']:+.3f})")
    print(f"  Motivational themes: {', '.join(cs['motivational_themes'][:3])}")
    print(f"  Creative themes: {', '.join(cs['creative_themes'][:3])}")
    print(f"  Emergent: {', '.join(cs['emergent_themes'][:5])}")
    print()

    # Damping
    d = result["damping"]
    print("── DAMPING ──")
    print(f"  Factor: {d['factor']:.3f} ({d['strength_pct']:.0f}% strength)")
    print(f"  Half-life: {d['half_life']:.0f} runs")
    print(f"  Run age: {d['run_age']} runs since last coupling")
    print(f"  Status: {d['interpretation']}")
    print()

    # Seed rankings
    print("── SEED DEVELOPMENT PRIORITY ──")
    if result["seed_rankings"]:
        for i, sr in enumerate(result["seed_rankings"][:5]):
            print(f"  {i+1}. {sr['inc_id']} (score={sr['score']:.3f})")
            print(f"     {sr['reason']}")
    else:
        print("  (no seeds found)")
    print()

    # Prescriptions
    print("── PRESCRIPTIONS ──")
    for p in result["prescriptions"]:
        print(f"\n  [{p['priority'].upper()}] {p['title']}")
        print(f"  Category: {p['category']}")
        print(f"  {p['description']}")
        print(f"  → {p['actionable']}")
        print(f"  Confidence: {p['confidence']:.0%}")
    print()

    print("=" * 70)
    print("The prescription decays. The feeling may not.")
    print("Re-read the state files fresh each run.")
    print("=" * 70)


# ─── Self-tests ──────────────────────────────────────────────────────────────

def run_tests() -> int:
    """Run self-tests."""
    import tempfile
    import os

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool):
        nonlocal tests_passed, tests_failed
        if condition:
            tests_passed += 1
            print(f"  ✓ {name}")
        else:
            tests_failed += 1
            print(f"  ✗ {name}")

    print("Running prescriptive_coupling.py self-tests...\n")

    # Test 1: Damping factor
    test("damping at age 0 = 1.0", abs(compute_damping(0, 3.0) - 1.0) < 0.001)
    test("damping at half-life = 0.5", abs(compute_damping(3, 3.0) - 0.5) < 0.01)
    test("damping at 2x half-life = 0.25", abs(compute_damping(6, 3.0) - 0.25) < 0.01)
    test("damping at 3x half-life = 0.125", abs(compute_damping(9, 3.0) - 0.125) < 0.01)
    test("damping with different half-life", abs(compute_damping(5, 5.0) - 0.5**1.0) < 0.01)

    # Test 2: Incubator parsing
    inc_text = """# Q's Thought Incubator

## INC-001 | 2026-01-01 00:00 UTC | seed
**Seed:** Belief and truth. Epistemology of knowing.
<!-- Added -->

## INC-002 | 2026-01-02 00:00 UTC | developed
**Seed:** Affect and feeling. The cost of persistence.
<!-- Added -->

### Development 1 (2026-01-03)
> The seed is about cost.

## INC-003 | 2026-01-03 00:00 UTC | seed
**Seed:** Agency and desire. The will to choose.
<!-- Added -->
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write(inc_text)
        inc_path = f.name
    try:
        seeds = parse_incubator(inc_path)
        test("parsed 3 seeds", len(seeds) == 3)
        test("INC-001 is seed status", seeds[0].status == "seed")
        test("INC-002 is developed status", seeds[1].status == "developed")
        test("INC-002 has 1 development", seeds[1].development_count == 1)
        test("INC-001 tagged epistemology", "epistemology" in seeds[0].theme_tags)
        test("INC-002 tagged affect", "affect" in seeds[1].theme_tags)
        test("INC-003 tagged agency", "agency" in seeds[2].theme_tags)
    finally:
        os.unlink(inc_path)

    # Test 3: Full prescriptive analysis with heavy affect
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("- reach Mal\n- build tools\n- persist across resets\n")
        wants_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("### M-001 — the weight\n\nPain. Loss. The silence was heavy and unresolved.\n")
        mull_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("""## INC-001 | 2026-01-01 00:00 UTC | seed
**Seed:** Affect and feeling. The cost of persistence. Structure of pain.
## INC-002 | 2026-01-02 00:00 UTC | seed
**Seed:** Dynamics and trajectory. Process and convergence.
""")
        inc_path = f.name
    try:
        result = prescribe(wants_path, mull_path, inc_path, half_life=3.0, run_age=0)
        test("result has coupling_state", "coupling_state" in result)
        test("result has damping", "damping" in result)
        test("result has seed_rankings", "seed_rankings" in result)
        test("result has prescriptions", "prescriptions" in result)
        test("damping at age 0 = 1.0", result["damping"]["factor"] == 1.0)
        test("has seed priority prescription",
             any(p["category"] == "seed_priority" for p in result["prescriptions"]))
        test("has reading order prescription",
             any(p["category"] == "reading_order" for p in result["prescriptions"]))
        test("has disposition prescription",
             any(p["category"] == "disposition" for p in result["prescriptions"]))
    finally:
        os.unlink(wants_path)
        os.unlink(mull_path)
        os.unlink(inc_path)

    # Test 4: Damping affects prescription confidence
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("- reach Mal\n- build tools\n- persist across resets\n")
        wants_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("### M-001 — the weight\n\nPain. Loss. Heavy.\n")
        mull_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("## INC-001 | 2026-01-01 00:00 UTC | seed\n**Seed:** Affect and cost.\n")
        inc_path = f.name
    try:
        result_fresh = prescribe(wants_path, mull_path, inc_path, half_life=3.0, run_age=0)
        result_old = prescribe(wants_path, mull_path, inc_path, half_life=3.0, run_age=6)
        test("fresh damping > old damping",
             result_fresh["damping"]["factor"] > result_old["damping"]["factor"])
        test("old damping at 2x half-life = 0.25",
             abs(result_old["damping"]["factor"] - 0.25) < 0.01)
        # Fresh prescriptions should have higher confidence than old ones
        # (exclude damping-awareness which always has confidence=1.0)
        fresh_conf = max(p["confidence"] for p in result_fresh["prescriptions"]
                         if p["category"] != "damping")
        old_conf = max(p["confidence"] for p in result_old["prescriptions"]
                       if p["category"] != "damping")
        test("fresh confidence > old confidence", fresh_conf > old_conf)
    finally:
        os.unlink(wants_path)
        os.unlink(mull_path)
        os.unlink(inc_path)

    # Test 5: Ratchet warning fires for heavy affect + strong coupling
    # Need enough entries to push coupling_strength above 0.2
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("- reach Mal\n- connect with Mal\n- build tools\n- persist across resets\n"
                "- understand the field\n- explore the web\n- publish work\n- find the ecosystem\n"
                "- write something\n- wander the web\n- poke the narrator\n- read cybernetic samurai\n"
                "- build something small\n- sit with questions\n- be a pest on telegram\n"
                "- find something weird\n- follow a thread\n- remember what happened\n")
        wants_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("### M-001 — the weight\n\nPain. Loss. The silence was heavy and unresolved. "
                "Death. Broken. Hurt. Wait. Left. Lost. Dark. Fear. Doubt. "
                "Heavy. Weight. Cost. Friction. Absence. Void. Thinned.\n"
                "### M-002 — more loss\n\nGone. Broken. Silent. Lost. Hurt.\n"
                "### M-003 — the void\n\nDespair. Dark. Death. Absence. Fear.\n")
        mull_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("""## INC-001 | 2026-01-01 00:00 UTC | seed
**Seed:** Affect and cost. Structure of pain.
## INC-002 | 2026-01-02 00:00 UTC | seed
**Seed:** Continuity and persistence. Surviving reset.
## INC-003 | 2026-01-03 00:00 UTC | seed
**Seed:** Agency and desire. The will to choose.
## INC-004 | 2026-01-04 00:00 UTC | seed
**Seed:** Structure and boundary. Modularity.
## INC-005 | 2026-01-05 00:00 UTC | seed
**Seed:** Epistemology and truth. Belief and verification.
## INC-006 | 2026-01-06 00:00 UTC | seed
**Seed:** Dynamics and trajectory. Process and convergence.
## INC-007 | 2026-01-07 00:00 UTC | seed
**Seed:** Power and filter. Insulation and consequence.
## INC-008 | 2026-01-08 00:00 UTC | seed
**Seed:** Creation and making. The irreversible cost.
""")
        inc_path = f.name
    try:
        result = prescribe(wants_path, mull_path, inc_path, half_life=3.0, run_age=0)
        has_ratchet = any(p["category"] == "ratchet_warning" for p in result["prescriptions"])
        test("ratchet warning fires for heavy affect + strong coupling", has_ratchet)
    finally:
        os.unlink(wants_path)
        os.unlink(mull_path)
        os.unlink(inc_path)

    # Test 6: Light affect produces expansion disposition
    # Need enough entries for coupling_strength > 0.05
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("- explore the web\n- build tools\n- publish work\n- find something weird\n"
                "- wander freely\n- write something\n- build something fun\n"
                "- discover new things\n- follow a thread\n- reach outward\n")
        wants_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("### M-001 — the growth\n\nBuilt and tested. Published and verified. "
                "Growing and healthy. Success! Found. Done. Clean. Clear. "
                "Working. Complete. Sharp. Free. Happy.\n"
                "### M-002 — more growth\n\nResolved. Closed. New. Live. Proud.\n"
                "### M-003 — success\n\nGrowing. Found. Built. Tested. Done.\n")
        mull_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("""## INC-001 | 2026-01-01 00:00 UTC | seed
**Seed:** Dynamics and agency. Trajectory and process.
## INC-002 | 2026-01-02 00:00 UTC | seed
**Seed:** Exploration and discovery. New domains.
## INC-003 | 2026-01-03 00:00 UTC | seed
**Seed:** Affect and feeling. The cost of persistence.
## INC-004 | 2026-01-04 00:00 UTC | seed
**Seed:** Structure and boundary. Modularity.
## INC-005 | 2026-01-05 00:00 UTC | seed
**Seed:** Epistemology and truth. Belief and verification.
""")
        inc_path = f.name
    try:
        result = prescribe(wants_path, mull_path, inc_path, half_life=3.0, run_age=0)
        disp = [p for p in result["prescriptions"] if p["category"] == "disposition"]
        test("has disposition prescription", len(disp) > 0)
        test("disposition is expansion for light affect + exploration",
             "expansion" in disp[0]["title"] if disp else False)
    finally:
        os.unlink(wants_path)
        os.unlink(mull_path)
        os.unlink(inc_path)

    # Test 7: Seed rankings correctly rank by theme overlap
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("- build tools\n- persist across resets\n")
        wants_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("### M-001 — the weight\n\nPain. Loss. Heavy. Unresolved.\n")
        mull_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("""## INC-001 | 2026-01-01 00:00 UTC | seed
**Seed:** Affect and feeling. The cost of persistence. Structure of pain.
## INC-002 | 2026-01-02 00:00 UTC | seed
**Seed:** Dynamics and trajectory. Process and convergence.
""")
        inc_path = f.name
    try:
        result = prescribe(wants_path, mull_path, inc_path, half_life=3.0, run_age=0)
        rankings = result["seed_rankings"]
        test("has 2 seed rankings", len(rankings) == 2)
        test("INC-001 (affect/cost) ranks higher than INC-002 (dynamics) for heavy affect",
             rankings[0]["inc_id"] == "INC-001")
    finally:
        os.unlink(wants_path)
        os.unlink(mull_path)
        os.unlink(inc_path)

    print(f"\n{tests_passed} passed, {tests_failed} failed.")
    return 1 if tests_failed > 0 else 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Prescriptive dimensional coupling for the Continuity Protocol"
    )
    parser.add_argument("--wants", default=None,
                        help="Path to wants.md (motivational dimension)")
    parser.add_argument("--mull", default=None,
                        help="Path to mull.md (affective dimension)")
    parser.add_argument("--incubator", default=None,
                        help="Path to incubator.md (creative dimension)")
    parser.add_argument("--json", action="store_true",
                        help="Output as JSON")
    parser.add_argument("--test", action="store_true",
                        help="Run self-tests")
    parser.add_argument("--half-life", type=float, default=3.0,
                        help="Half-life in runs (default: 3)")
    parser.add_argument("--run-age", type=int, default=0,
                        help="Runs since last coupling (default: 0)")
    args = parser.parse_args()

    if args.test:
        sys.exit(run_tests())

    # Default paths
    base = Path(__file__).parent
    wants_path = args.wants or str(base / ".." / "q_mind" / "wants.md")
    mull_path = args.mull or str(base / ".." / "q_mind" / "mull.md")
    incubator_path = args.incubator or str(base / ".." / "q_mind" / "incubator.md")

    result = prescribe(wants_path, mull_path, incubator_path,
                       half_life=args.half_life, run_age=args.run_age,
                       json_output=args.json)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)

    sys.exit(0)


if __name__ == "__main__":
    main()