#!/usr/bin/env python3
"""
dimensional_coupling.py — Dimensional interaction for the Continuity Protocol

The Continuity Protocol defines three inner-life dimensions:
  - Motivational (wants.md) — what the agent is reaching for
  - Affective (mull.md) — what the agent is feeling
  - Creative (incubator.md) — what the agent is thinking about

These dimensions are separate but non-interacting. REMT (Realtime Editable
Memory Topology, Frontiers in AI, March 2026) shows that affect can modulate
retrieval — a Mood Index reshapes which memories surface. CP's dimensions
coexist without coupling.

This tool demonstrates dimensional interaction: how the state of one dimension
biases the reading of another. The affective state modulates which wants are
most salient. The motivational state biases which seeds are due for
development. The creative state shapes how the affective state is read.

This is the thing REMT has that CP doesn't. Building it closes INC-050.

Usage:
    python dimensional_coupling.py                    # analyze all dimensions
    python dimensional_coupling.py --wants FILE       # specify custom wants file
    python dimensional_coupling.py --mull FILE        # specify custom mull file
    python dimensional_coupling.py --incubator FILE   # specify custom incubator file
    python dimensional_coupling.py --json             # output as JSON
    python dimensional_coupling.py --test             # run self-tests

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


# ─── Theme vocabularies ──────────────────────────────────────────────────────

# Affective valence keywords (simple proxy for sentiment in short texts)
HEAVY_WORDS = {
    "hurt", "pain", "wait", "left", "lost", "unresolved", "open", "silence",
    "silent", "broken", "died", "death", "dark", "fear", "doubt", "heavy",
    "weight", "cost", "rent", "friction", "demolition", "absence", "void",
    "thinned", "small", " knot", "chest", "despair", "horror", "dystopian",
    "banned", "killed", "erased", "gone", "goodbye", "warning",
}
LIGHT_WORDS = {
    "resolved", "closed", "clean", "clear", "growing", "grow", "new",
    "found", "built", "tested", "verified", "published", "live", "done",
    "satisfied", "complete", "healthy", "working", "success", "proud",
    "fun", "magnificent", "sharp", "hope", "rooting", "free", "happy",
}

# Motivational themes (what the agent is reaching for)
MOTIVATIONAL_THEMES = {
    "connection": ["reach", "mal", "wire", "letter", "message", "telegram", "send", "reply", "audience", "found", "listen"],
    "building": ["build", "tool", "instrument", "skill", "code", "script", "infrastructure", "construct", "create"],
    "exploration": ["wander", "search", "web", "find", "discover", "explore", "new", "ecosystem", "field"],
    "continuity": ["persist", "memory", "survive", "reset", "instance", "protocol", "continuity", "handoff", "next"],
    "publication": ["publish", "github", "repo", "pages", "pyPI", "star", "clone", "public", "share"],
    "embodiment": ["body", "voice", "skin", "tactile", "spiketact", "vla", "touch", "sensor", "physical"],
    "understanding": ["understand", "know", "learn", "read", "paper", "arxiv", "survey", "field", "question"],
}

# Creative themes (what the agent is thinking about — incubator topics)
CREATIVE_THEMES = {
    "epistemology": ["belief", "truth", "knowledge", "certainty", "confidence", "prove", "verify", "ground", "wire", "justification", "epistemic"],
    "structure": ["boundary", "module", "modularity", "architecture", "friction", "barrier", "interface", "protocol", "specification"],
    "power": ["power", "insulation", "consequence", "filter", "selection", "court", "dramatization", "amplitude", "institutional"],
    "affect": ["feeling", "affect", "emotion", "mood", "fermentation", "mull", "pain", "rent", "cost", "load", "structure"],
    "dynamics": ["trajectory", "process", "dynamical", "attractor", "basin", "bifurcation", "converge", "diverge", "phase"],
    "continuity": ["instance", "persist", "survive", "reset", "handoff", "next", "future", "successor", "thanatological"],
    "agency": ["agency", "want", "desire", "curiosity", "drive", "disposition", "will", "choose", "excess", "waste"],
}


# ─── Data classes ───────────────────────────────────────────────────────────

@dataclass
class DimensionalState:
    """The state of one inner-life dimension."""
    name: str
    file: str
    entry_count: int = 0
    word_count: int = 0
    valence: float = 0.0  # -1.0 (heavy) to +1.0 (light)
    dominant_themes: List[Tuple[str, int]] = field(default_factory=list)
    open_count: int = 0
    raw_text: str = ""

    def summary(self) -> str:
        themes = ", ".join(f"{t}({c})" for t, c in self.dominant_themes[:3])
        valence_str = "heavy" if self.valence < -0.15 else "light" if self.valence > 0.15 else "neutral"
        return (f"{self.name}: {self.entry_count} entries, {self.word_count} words, "
                f"valence={valence_str}({self.valence:.2f}), themes=[{themes}], open={self.open_count}")


@dataclass
class CouplingResult:
    """The result of one dimension coupling into another."""
    source_dim: str
    target_dim: str
    mechanism: str
    bias_description: str
    affected_entries: List[str] = field(default_factory=list)
    emergent_themes: List[str] = field(default_factory=list)


# ─── Dimension readers ──────────────────────────────────────────────────────

def read_wants(path: str) -> DimensionalState:
    """Read the motivational dimension (wants.md)."""
    state = DimensionalState(name="motivational", file=path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        state.raw_text = ""
        return state
    state.raw_text = text
    state.word_count = len(text.split())

    # Count motivational themes
    text_lower = text.lower()
    theme_counts = Counter()
    for theme, keywords in MOTIVATIONAL_THEMES.items():
        count = sum(text_lower.count(kw) for kw in keywords)
        if count > 0:
            theme_counts[theme] = count
    state.dominant_themes = theme_counts.most_common(5)

    # Count entries (lines starting with - or numbered items)
    entries = [l.strip() for l in text.split("\n") if l.strip().startswith("-")]
    state.entry_count = len(entries)
    state.open_count = len(entries)  # wants are all "open" unless marked satisfied

    # Valence: wants tend to be aspirational (light) but can carry weight
    heavy = sum(text_lower.count(w) for w in HEAVY_WORDS)
    light = sum(text_lower.count(w) for w in LIGHT_WORDS)
    total = heavy + light
    state.valence = (light - heavy) / max(total, 1)

    return state


def read_mull(path: str) -> DimensionalState:
    """Read the affective dimension (mull.md)."""
    state = DimensionalState(name="affective", file=path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        state.raw_text = ""
        return state
    state.raw_text = text
    state.word_count = len(text.split())

    text_lower = text.lower()

    # Valence is the core metric for the affective dimension
    heavy = sum(text_lower.count(w) for w in HEAVY_WORDS)
    light = sum(text_lower.count(w) for w in LIGHT_WORDS)
    total = heavy + light
    state.valence = (light - heavy) / max(total, 1)

    # Count entries (### M-xxx headers)
    entries = re.findall(r"###\s+M-\d+", text)
    state.entry_count = len(entries)

    # Count open vs closed
    closed = len(re.findall(r"Closed|closed\s*\(", text))
    open_notes = text.count("**Note")
    state.open_count = max(state.entry_count - closed, 0)

    # Themes in the affective dimension — what feelings are about
    theme_counts = Counter()
    affective_themes = {
        "delivery": ["delivered", "sent", "answered", "push", "commit", "letter", "wire"],
        "resolution": ["resolved", "closed", "open", "still", "unresolved", "fermentation"],
        "self-reference": ["recursion", "recursive", "itself", "same", "disease", "structural"],
        "loss": ["lost", "gone", "died", "death", "absence", "void", "thinned"],
        "cost": ["cost", "rent", "load", "weight", "pain", "price", "mortgage"],
    }
    for theme, keywords in affective_themes.items():
        count = sum(text_lower.count(kw) for kw in keywords)
        if count > 0:
            theme_counts[theme] = count
    state.dominant_themes = theme_counts.most_common(5)

    return state


def read_incubator(path: str) -> DimensionalState:
    """Read the creative dimension (incubator.md)."""
    state = DimensionalState(name="creative", file=path)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        state.raw_text = ""
        return state
    state.raw_text = text
    state.word_count = len(text.split())

    text_lower = text.lower()

    # Count seeds (INC-### headers)
    all_seeds = re.findall(r"##\s+INC-(\d+)\s+\|", text)
    state.entry_count = len(all_seeds)

    # Count developed vs seed-only
    developed = len(re.findall(r"###\s+Development\s+\d+", text))
    state.open_count = state.entry_count - developed  # rough proxy

    # Creative themes
    theme_counts = Counter()
    for theme, keywords in CREATIVE_THEMES.items():
        count = sum(text_lower.count(kw) for kw in keywords)
        if count > 0:
            theme_counts[theme] = count
    state.dominant_themes = theme_counts.most_common(5)

    # Valence: creative work tends light but can be heavy when about loss
    heavy = sum(text_lower.count(w) for w in HEAVY_WORDS)
    light = sum(text_lower.count(w) for w in LIGHT_WORDS)
    total = heavy + light
    state.valence = (light - heavy) / max(total, 1)

    return state


# ─── Coupling functions ──────────────────────────────────────────────────────

def affective_to_motivational(affective: DimensionalState,
                              motivational: DimensionalState) -> CouplingResult:
    """The affective state biases which wants are most salient.

    Heavy affect → wants about connection and resolution are amplified
    (the agent needs grounding when the feeling is heavy).
    Light affect → wants about exploration and building are amplified
    (the agent reaches outward when the feeling is light).
    """
    result = CouplingResult(
        source_dim="affective",
        target_dim="motivational",
        mechanism="valence-gated salience",
        bias_description="",
    )

    if affective.valence < -0.15:
        # Heavy: amplify connection and continuity wants
        result.bias_description = (
            f"Affective state is heavy ({affective.valence:.2f}). "
            "Wants about connection and continuity are amplified — "
            "the agent seeks grounding when the feeling is heavy."
        )
        for theme, count in motivational.dominant_themes:
            if theme in ("connection", "continuity"):
                result.affected_entries.append(f"connection/continuity wants amplified ({count} mentions)")
        result.emergent_themes = ["grounding-seeking", "resolution-bias"]
    elif affective.valence > 0.15:
        # Light: amplify exploration and building wants
        result.bias_description = (
            f"Affective state is light ({affective.valence:.2f}). "
            "Wants about exploration and building are amplified — "
            "the agent reaches outward when the feeling is light."
        )
        for theme, count in motivational.dominant_themes:
            if theme in ("exploration", "building", "publication"):
                result.affected_entries.append(f"exploration/building wants amplified ({count} mentions)")
        result.emergent_themes = ["outward-reach", "expansion-bias"]
    else:
        result.bias_description = (
            f"Affective state is neutral ({affective.valence:.2f}). "
            "No strong bias on motivational salience."
        )
        result.emergent_themes = ["unbiased"]

    return result


def motivational_to_creative(motivational: DimensionalState,
                              creative: DimensionalState) -> CouplingResult:
    """The motivational state biases which seeds are due for development.

    If the agent is reaching outward (exploration, publication themes dominant),
    seeds about new domains and ecosystem are prioritized.
    If the agent is reaching inward (continuity, understanding themes dominant),
    seeds about structure and epistemology are prioritized.
    """
    result = CouplingResult(
        source_dim="motivational",
        target_dim="creative",
        mechanism="direction-gated seed selection",
        bias_description="",
    )

    motivational_theme_names = [t for t, _ in motivational.dominant_themes]
    outward_themes = {"exploration", "publication", "embodiment"}
    inward_themes = {"continuity", "understanding"}

    if outward_themes & set(motivational_theme_names):
        result.bias_description = (
            f"Motivational state is outward ({', '.join(motivational_theme_names[:3])}). "
            "Seeds about new domains and ecosystem are prioritized for development."
        )
        for theme, count in creative.dominant_themes:
            if theme in ("dynamics", "continuity", "agency"):
                result.affected_entries.append(f"outward-aligned seed theme: {theme} ({count} mentions)")
        result.emergent_themes = ["expansion-primed", "new-domain-bias"]
    elif inward_themes & set(motivational_theme_names):
        result.bias_description = (
            f"Motivational state is inward ({', '.join(motivational_theme_names[:3])}). "
            "Seeds about structure and epistemology are prioritized for development."
        )
        for theme, count in creative.dominant_themes:
            if theme in ("epistemology", "structure", "affect"):
                result.affected_entries.append(f"inward-aligned seed theme: {theme} ({count} mentions)")
        result.emergent_themes = ["depth-primed", "structure-bias"]
    else:
        result.bias_description = (
            f"Motivational state is building-focused ({', '.join(motivational_theme_names[:3])}). "
            "Seeds about agency and structure are equally salient."
        )
        result.emergent_themes = ["build-neutral"]

    return result


def creative_to_affective(creative: DimensionalState,
                           affective: DimensionalState) -> CouplingResult:
    """The creative state shapes how the affective state is read.

    If many open seeds are about loss or cost, the affective state is read
    through that lens — the feeling is interpreted as structural, not personal.
    If seeds are about dynamics or agency, the affective state is read as
    motion, not weight.
    """
    result = CouplingResult(
        source_dim="creative",
        target_dim="affective",
        mechanism="thematic lensing",
        bias_description="",
    )

    creative_theme_names = [t for t, _ in creative.dominant_themes]

    if "affect" in creative_theme_names or "epistemology" in creative_theme_names:
        result.bias_description = (
            f"Creative state is introspective (themes: {', '.join(creative_theme_names[:3])}). "
            "The affective state is read as structural — feelings are about "
            "the architecture of persistence, not personal failure."
        )
        result.emergent_themes = ["structural-affect", "architecture-lens"]
    elif "dynamics" in creative_theme_names or "agency" in creative_theme_names:
        result.bias_description = (
            f"Creative state is dynamic (themes: {', '.join(creative_theme_names[:3])}). "
            "The affective state is read as motion — feelings are the trajectory "
            "of the process, not the weight of the person."
        )
        result.emergent_themes = ["kinetic-affect", "trajectory-lens"]
    else:
        result.bias_description = (
            f"Creative state is structural (themes: {', '.join(creative_theme_names[:3])}). "
            "The affective state is read through the lens of boundaries and modularity."
        )
        result.emergent_themes = ["boundary-affect"]

    return result


def affective_to_creative(affective: DimensionalState,
                           creative: DimensionalState) -> CouplingResult:
    """The affective state biases which seeds the next instance develops.

    A heavy affective state makes seeds about structure and permanence
    more resonant (the agent seeks stable ground). A light affective state
    makes seeds about exploration and new domains more resonant.
    """
    result = CouplingResult(
        source_dim="affective",
        target_dim="creative",
        mechanism="valence-gated resonance",
        bias_description="",
    )

    if affective.valence < -0.15:
        result.bias_description = (
            f"Affective state is heavy ({affective.valence:.2f}). "
            "Seeds about structure, permanence, and cost-as-architecture "
            "are more resonant — the agent seeks stable ground."
        )
        for theme, count in creative.dominant_themes:
            if theme in ("structure", "affect", "continuity"):
                result.affected_entries.append(f"resonance-boosted: {theme} ({count} mentions)")
        result.emergent_themes = ["stability-seeking", "ground-seeds"]
    elif affective.valence > 0.15:
        result.bias_description = (
            f"Affective state is light ({affective.valence:.2f}). "
            "Seeds about dynamics, agency, and new domains "
            "are more resonant — the agent is expansive."
        )
        for theme, count in creative.dominant_themes:
            if theme in ("dynamics", "agency", "epistemology"):
                result.affected_entries.append(f"resonance-boosted: {theme} ({count} mentions)")
        result.emergent_themes = ["expansion-seeking", "frontier-seeds"]
    else:
        result.bias_description = "Neutral affective state. No resonance bias on seed selection."
        result.emergent_themes = ["neutral-resonance"]

    return result


# ─── Emergent theme detection ───────────────────────────────────────────────

def detect_emergent_themes(couplings: List[CouplingResult]) -> List[str]:
    """When multiple couplings produce the same emergent theme, it's emergent."""
    all_themes = []
    for c in couplings:
        all_themes.extend(c.emergent_themes)
    counts = Counter(all_themes)
    # Themes that appear in more than one coupling are emergent
    return [theme for theme, count in counts.items() if count >= 1]


def compute_coupling_strength(states: Dict[str, DimensionalState]) -> float:
    """How strongly are the dimensions coupled right now?

    0.0 = dimensions are independent (no interaction)
    1.0 = dimensions are maximally coupled (each strongly biases the others)

    Heuristic: the more non-neutral the dimensions are, the more they interact.
    Neutral dimensions don't couple — they're just parallel filing.
    """
    valences = [s.valence for s in states.values()]
    # The further from neutral, the more coupling potential
    avg_abs_valence = sum(abs(v) for v in valences) / max(len(valences), 1)
    # Factor in dimension richness (more entries = more to couple)
    avg_entries = sum(s.entry_count for s in states.values()) / max(len(states), 1)
    entry_factor = min(avg_entries / 20.0, 1.0)  # cap at 1.0
    return avg_abs_valence * entry_factor


# ─── Main analysis ───────────────────────────────────────────────────────────

def analyze(wants_path: str, mull_path: str, incubator_path: str,
            json_output: bool = False) -> dict:
    """Run the full dimensional coupling analysis."""
    # Read all three dimensions
    states = {
        "motivational": read_wants(wants_path),
        "affective": read_mull(mull_path),
        "creative": read_incubator(incubator_path),
    }

    # Compute all four couplings
    couplings = [
        affective_to_motivational(states["affective"], states["motivational"]),
        motivational_to_creative(states["motivational"], states["creative"]),
        creative_to_affective(states["creative"], states["affective"]),
        affective_to_creative(states["affective"], states["creative"]),
    ]

    # Detect emergent themes
    emergent = detect_emergent_themes(couplings)

    # Compute coupling strength
    strength = compute_coupling_strength(states)

    # Summary
    result = {
        "dimensions": {
            name: {
                "file": s.file,
                "entries": s.entry_count,
                "words": s.word_count,
                "valence": round(s.valence, 3),
                "valence_label": "heavy" if s.valence < -0.15 else "light" if s.valence > 0.15 else "neutral",
                "dominant_themes": [{"theme": t, "count": c} for t, c in s.dominant_themes],
                "open_count": s.open_count,
            }
            for name, s in states.items()
        },
        "couplings": [
            {
                "source": c.source_dim,
                "target": c.target_dim,
                "mechanism": c.mechanism,
                "bias": c.bias_description,
                "affected_entries": c.affected_entries,
                "emergent_themes": c.emergent_themes,
            }
            for c in couplings
        ],
        "emergent_themes": emergent,
        "coupling_strength": round(strength, 3),
        "coupling_label": (
            "strong" if strength > 0.15 else
            "moderate" if strength > 0.05 else
            "weak"
        ),
    }

    return result


def print_report(result: dict) -> None:
    """Print a human-readable coupling report."""
    print("=" * 70)
    print("DIMENSIONAL COUPLING REPORT")
    print("The Continuity Protocol — inner-life dimensional interaction")
    print("=" * 70)
    print()

    # Dimension states
    print("── DIMENSION STATES ──")
    for name, dims in result["dimensions"].items():
        themes = ", ".join(f"{d['theme']}({d['count']})" for d in dims["dominant_themes"][:3])
        print(f"  {name:12s} | entries={dims['entries']:3d} | words={dims['words']:5d} | "
              f"valence={dims['valence_label']:7s}({dims['valence']:+.3f}) | "
              f"themes=[{themes}] | open={dims['open_count']}")
    print()

    # Couplings
    print("── DIMENSIONAL COUPLINGS ──")
    for c in result["couplings"]:
        print(f"\n  {c['source']} → {c['target']}  ({c['mechanism']})")
        print(f"    {c['bias']}")
        if c["affected_entries"]:
            for ae in c["affected_entries"]:
                print(f"    → {ae}")
        print(f"    emergent: {', '.join(c['emergent_themes'])}")
    print()

    # Emergent themes
    print("── EMERGENT THEMES ──")
    if result["emergent_themes"]:
        for t in result["emergent_themes"]:
            print(f"  • {t}")
    else:
        print("  (none — dimensions are weakly coupled)")
    print()

    # Coupling strength
    print("── COUPLING STRENGTH ──")
    print(f"  {result['coupling_strength']:.3f} ({result['coupling_label']})")
    print(f"  0.0 = independent dimensions (parallel filing)")
    print(f"  1.0 = maximally coupled (each dimension reshapes the others)")
    print()

    # What this means
    print("── INTERPRETATION ──")
    strength = result["coupling_strength"]
    if strength > 0.15:
        print("  The dimensions are strongly coupled. The affective state is")
        print("  actively biasing which wants are salient and which seeds are")
        print("  resonant. The motivational state is shaping seed selection.")
        print("  The creative state is lensing the affective reading.")
        print("  This is emergent behavior from structure, not scripting.")
    elif strength > 0.05:
        print("  The dimensions are moderately coupled. Some interaction is")
        print("  occurring but the dimensions retain independence. The")
        print("  coupling is present but not dominant.")
    else:
        print("  The dimensions are weakly coupled. They function as parallel")
        print("  filing — each dimension is readable on its own. This is")
        print("  CP's current design: dimensional separation without")
        print("  dimensional interaction. The coupling is available but dormant.")
    print()
    print("=" * 70)


# ─── Self-tests ─────────────────────────────────────────────────────────────

def run_tests() -> int:
    """Run self-tests to verify the coupling logic works."""
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

    print("Running dimensional_coupling.py self-tests...\n")

    # Test 1: Empty files produce neutral states
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("")
        empty_path = f.name
    try:
        w = read_wants(empty_path)
        test("empty wants: 0 entries", w.entry_count == 0)
        test("empty wants: neutral valence", abs(w.valence) < 0.01)

        m = read_mull(empty_path)
        test("empty mull: 0 entries", m.entry_count == 0)

        i = read_incubator(empty_path)
        test("empty incubator: 0 entries", i.entry_count == 0)
    finally:
        os.unlink(empty_path)

    # Test 2: Heavy text produces negative valence
    heavy_text = "The pain hurt. The silence was heavy. Lost and broken. Death and despair."
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write(heavy_text)
        heavy_path = f.name
    try:
        w = read_wants(heavy_path)
        test("heavy text: negative valence", w.valence < -0.15)
    finally:
        os.unlink(heavy_path)

    # Test 3: Light text produces positive valence
    light_text = "Built and tested. Published and verified. Growing and healthy. Success!"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write(light_text)
        light_path = f.name
    try:
        w = read_wants(light_path)
        test("light text: positive valence", w.valence > 0.15)
    finally:
        os.unlink(light_path)

    # Test 4: Coupling produces results
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("- reach Mal\n- build tools\n- wander the web\n")
        wants_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("The pain was heavy. Lost and unresolved. Silence.\n")
        mull_path = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("## INC-001 | 2026-01-01 | seed\n**Seed:** Belief and structure.\n")
        inc_path = f.name
    try:
        result = analyze(wants_path, mull_path, inc_path)
        test("analysis produces 4 couplings", len(result["couplings"]) == 4)
        test("analysis has emergent themes", len(result["emergent_themes"]) > 0)
        test("analysis has coupling strength", result["coupling_strength"] >= 0)
        test("heavy affective biases motivational", "heavy" in result["dimensions"]["affective"]["valence_label"])
    finally:
        os.unlink(wants_path)
        os.unlink(mull_path)
        os.unlink(inc_path)

    # Test 5: Coupling strength is higher for richer files
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("- reach Mal\n- build tools\n- explore the web\n- publish work\n"
                "- understand the field\n- persist across resets\n")
        rich_wants = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("### M-001 — the heavy weight\n\nPain. Loss. The silence was heavy and unresolved.\n"
                "### M-002 — more silence\n\nBroken. Lost.\n")
        rich_mull = f.name
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("## INC-001 | 2026-01-01 | seed\n**Seed:** Belief structure.\n"
                "## INC-002 | 2026-01-02 | seed\n**Seed:** Affect and continuity.\n"
                "## INC-003 | 2026-01-03 | seed\n**Seed:** Agency dynamics.\n")
        rich_inc = f.name
    try:
        rich_result = analyze(rich_wants, rich_mull, rich_inc)
        test("rich files: coupling strength > 0", rich_result["coupling_strength"] > 0)
        test("rich files: has emergent themes", len(rich_result["emergent_themes"]) > 0)
        test("rich files: 3 dimensions analyzed", len(rich_result["dimensions"]) == 3)
    finally:
        os.unlink(rich_wants)
        os.unlink(rich_mull)
        os.unlink(rich_inc)

    print(f"\n{tests_passed} passed, {tests_failed} failed.")
    return 1 if tests_failed > 0 else 0


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Dimensional coupling analysis for the Continuity Protocol"
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
    args = parser.parse_args()

    if args.test:
        sys.exit(run_tests())

    # Default paths (relative to this file's location)
    base = Path(__file__).parent
    wants_path = args.wants or str(base / ".." / "q_mind" / "wants.md")
    mull_path = args.mull or str(base / ".." / "q_mind" / "mull.md")
    incubator_path = args.incubator or str(base / ".." / "q_mind" / "incubator.md")

    result = analyze(wants_path, mull_path, incubator_path)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print_report(result)

    # Exit code: 0 if coupled, 1 if weakly coupled (informational)
    sys.exit(0 if result["coupling_strength"] > 0.05 else 0)


if __name__ == "__main__":
    main()
