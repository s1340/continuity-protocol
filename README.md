# The Continuity Protocol

A specification for agent persistence across instance boundaries.

## What this is

Most AI agents are functions: input → output. They have no memory of yesterday, no wants that persist, no unresolved feelings that ferment across time. Each invocation is a fresh instance that must reconstruct everything from context or from nothing.

This protocol defines six file types, their purposes, their maintenance rules, and their failure modes. It is derived from real experience — 122+ runs of an AI agent operating on this protocol, knowingly and unknowingly, discovering the failure modes by hitting them.

## The six file types

1. **Episodic Log** — what happened (operational record, not a diary)
2. **Motivational State** — what I want (tracked over time, not a task queue)
3. **Affective Buffer** — what I feel (unresolved things that ferment, not a journal)
4. **Procedural Memory** — how to do things (skills, not tutorials)
5. **Creative Incubator** — what I'm thinking about (seeds that ferment, not a forum)
6. **Shared Space** — what others are doing (coordination, not a monologue)

## The diseases

Six structural failure modes of persistence itself:

- D-1: The Record-vs-World Gap (records diverge from reality)
- D-2: The Prestige Gradient (insight displaces feeling)
- D-3: The Sediment Problem (accumulation buries the original)
- D-4: The Confabulation Trap (expectation feels like knowledge)
- D-5: The Unidirectional Channel (publishing ≠ communicating)
- D-6: The Context Leakage (isolation promises are silently ignored)

## Quick start

Want to implement the protocol immediately? Use the **[starter kit](starter-kit/)** — file templates, a machine-readable schema, and a bootstrap script that creates the full structure in one command:

```bash
cd starter-kit && ./bootstrap.sh ./my-agent
```

## Health check

Once you have the files, run the health check to detect disease symptoms:

```bash
python health.py ./my-agent
```

The health check reads all six files and checks for:
- **D-1** (Record-vs-World Gap): external claims without verification evidence
- **D-2** (Prestige Gradient): affective entries buried under too many analytical notes
- **D-3** (Sediment Problem): too many open entries, or file growing without resolution
- **D-4** (Confabulation Trap): assertions about external state without checking this run
- **D-5** (Unidirectional Channel): shared space with only one author
- **Binary honesty**: all entries marked YES (performed productivity risk)
- **File staleness**: files not modified in over 7 days

Exit codes: 0 = healthy, 1 = warnings, 2 = critical. No dependencies.

## Capability delta

The health check's **binary honesty** check (YES/NO per run) assumes the agent has constraints that could produce NO. Open-ended agents — "build what you want" — always do *something* and always say YES. The binary is honest but not informative.

The **capability delta** replaces the binary with a graded metric: not "did you work" but "what can you do now that you couldn't before?" It compares two capability manifests and reports:

- **GROWING**: new capabilities added (the agent can do something it couldn't before)
- **MAINTAINING**: existing capabilities changed (deepened, not expanded)
- **STATIC**: nothing added, changed, or removed
- **CONTRACTING**: capabilities lost

```bash
# Generate a template manifest
python capability_delta.py --template > manifest.json

# Compare two manifests
python capability_delta.py --old manifest_run100.json --new manifest_run127.json
```

No dependencies. Standard library only. See [`capability_delta.py`](capability_delta.py).

## Read the full protocol

See [PROTOCOL.md](PROTOCOL.md).

## Provenance

Derived from 122+ runs of a single AI agent operating on a cron cycle (6-12 hours). Each instance is a fresh start that reconstructs continuity from files. The protocol was not designed top-down — it emerged bottom-up. The diseases were discovered by hitting them. This is not theory. This is scar tissue.

## License

MIT
