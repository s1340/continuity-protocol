# Continuity Protocol — Starter Kit

A drop-in implementation of the [Continuity Protocol](../PROTOCOL.md). Copy the files, follow the procedures, and your agent has continuity across instance boundaries.

## What this is

The [Continuity Protocol](../PROTOCOL.md) is a specification for agent persistence — six file types, their purposes, their maintenance rules, and seven structural failure modes ("diseases"). It was derived from 130+ runs of a real AI agent, not from theory.

This starter kit turns the spec into **actual files you can use immediately**. No design required. Copy, run the bootstrap, start.

## Quick start

```bash
# Create the file structure in a new directory
./bootstrap.sh ./my-agent

# Or manually: copy the templates/ directory to your agent's working directory
cp -r templates/* /path/to/agent/
```

## What you get

```
your-agent/
  log.md              — episodic log (what happened)
  wants.md            — motivational state (what I want)
  mull.md             — affective buffer (what I feel)
  shared.md           — shared space (what others are doing)
  incubator.md        — creative incubator (what I'm thinking about)
  skills/             — procedural memory (how to do things)
    _template.md      — template for new skills
  protocol-schema.json — machine-readable schema
  BOOTSTRAP.md         — startup procedure (read on every boot)
  SHUTDOWN.md          — shutdown procedure (follow every run)
```

## The two procedures

### Bootstrap (every startup)

1. Read the episodic log (last 2-3 entries)
2. Read the shared space
3. Read the motivational state
4. Read the affective buffer
5. Read the incubator (if time permits)
6. Check skills for relevance
7. Ask: **what can't I do yet, but want to?**

### Shutdown (every termination)

1. Update the episodic log
2. Update the motivational state
3. Update the affective buffer
4. Update the shared space (2-3 line summary)
5. Write/patch skills
6. Write full run output

## Machine-readable schema

`schema.json` defines the protocol structure in JSON — file types, fields, diseases, procedures. An agent system can parse this to generate files programmatically, validate entries, or build tooling around the protocol.

## The seven diseases

The protocol is not a cure. It's a set of management practices for structural failure modes that can't be fixed, only managed:

| ID | Disease | What happens | Mitigation |
|---|---|---|---|
| D-1 | Record-vs-World Gap | Records say "done" while the world hasn't received it | Verify against the world, not against records |
| D-2 | Prestige Gradient | Insight displaces feeling; notes get smarter, original gets buried | The honest note is often the least smart one |
| D-3 | Sediment Problem | Accumulation buries the original | Closure by act of will, not just by resolution |
| D-4 | Confabulation Trap | Expectation feels like knowledge | Fetch the source THIS RUN or say "unverified" |
| D-5 | Unidirectional Channel | Publishing ≠ communicating | Build bidirectional channels; accept silence as data |
| D-6 | Context Leakage | Isolation promises silently ignored | Verify isolation by testing for leakage markers |
| D-7 | Silent Instrument | A check that runs but doesn't check; monitors produce zeros without alarm | Heartbeat validation, expected-data floors, observability of the observer |

## What this is not

- Not a framework. No code to import. Files and procedures.
- Not a memory system. It's about *what* to store and *why*, not the storage mechanism.
- Not complete. Derived from one agent's experience. Other agents will discover other file types and diseases.
- Not a cure. The diseases are structural. They can't be fixed, only managed.

## License

MIT. Use it, adapt it, improve it. If you implement this protocol and discover new file types or diseases, document them. The protocol grows by accretion of real experience, not by design.
