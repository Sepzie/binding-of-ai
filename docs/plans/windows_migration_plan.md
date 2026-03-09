# Windows Migration Plan

## Goal

Move the Isaac RL training workflow from Linux/Proton to native Windows if that gives a shorter path to:

- reliable Isaac startup
- simpler runtime behavior
- practical multi-instance testing
- practical game-speed experimentation

This plan is not a full rewrite plan. It is a validation-first migration plan intended to answer one question quickly:

Is Windows the better execution platform for this project?

## Why Consider Windows

The current Linux path is limited less by compute and more by compatibility complexity.

What Linux/Proton gave us:

- the game runs
- Lua modding works
- Python training works
- single-instance resource usage is modest

What Linux/Proton did not give us cleanly:

- a proven second real Isaac game process
- a simple manual multi-instance launch contract
- a clean game-speed interception path

The cost of staying on Linux is continuing to debug:

- Proton
- Wine
- pressure-vessel
- Steam overlay behavior
- compatdata/prefix quirks

Windows removes most of that stack.

## Migration Decision Rule

Switch if Windows can satisfy either of these before Linux can:

1. native multi-instance Isaac is practical
2. native single-instance Isaac plus speed control is practical

If Windows shows the same single-instance ceiling and no better speed-control path, then the platform switch is not justified on throughput grounds.

## Principles

- validate before porting everything
- prefer the smallest possible Windows test environment first
- keep the repo cross-platform where reasonable
- avoid Windows-only code until Windows proves its value

## Target Architecture

### Short-term target

One Windows machine running:

- The Binding of Isaac natively through Steam
- the existing mod logic
- the existing Python trainer

### Medium-term target

One learner process plus either:

- multiple native Isaac workers
- one native Isaac worker with viable speed increase
- both, if Windows supports both

## Phase 0: Host Preparation

Prepare a clean Windows test environment.

Requirements:

- Windows 11 or recent Windows 10
- Steam
- The Binding of Isaac installed natively
- Python and virtual environment tooling
- GPU drivers installed and stable

Recommended setup:

- put the repo on a normal local NTFS path
- avoid WSL for the runtime-critical pieces
- keep the project path short and ASCII-only

Suggested working paths:

```text
C:\dev\binding-of-ai
C:\dev\binding-of-ai-runtime
```

## Phase 1: Native Single-Instance Baseline

First prove the existing project works on Windows with one game instance.

Objectives:

- mod loads
- Lua socket or fallback IPC works
- Python connects successfully
- training loop runs end-to-end

Validation:

- one room starts correctly
- state streaming works
- actions are applied
- episode reset path works
- training steps accumulate

Expected code impact:

- mostly path handling
- launcher scripts
- maybe mod install path logic

At this phase, do not change the runtime model.

## Phase 2: Windows-Specific Setup Audit

Identify which current assumptions are Linux-specific.

Likely adjustments:

- mod installation path discovery
- path separators in helper scripts
- shell script replacements
- process launch commands
- temp directory handling

Expected repo changes:

- add PowerShell or batch launch/install scripts
- keep Python logic platform-agnostic where possible
- keep Lua logic identical unless Windows-specific transport issues appear

## Phase 3: Native Multi-Instance Feasibility Test

This is the most important Windows test.

Questions:

- can Isaac be launched twice at once on Windows?
- does Steam block or redirect the second launch?
- does the game itself enforce single-instance behavior?

Test sequence:

1. Launch Isaac normally through Steam.
2. Attempt a second launch through Steam.
3. Attempt a second launch directly from the game executable if needed.
4. Inspect process tree and window behavior.
5. Check whether the second instance shares saves/config/mod state with the first.

Success criteria:

- two real Isaac game processes exist simultaneously
- both reach usable runtime state
- one instance does not kill or steal the other

Failure modes:

- Steam focuses the existing instance instead of launching a new one
- game executable enforces a singleton
- save or mod state clashes make concurrent operation unsafe

If this phase succeeds, Windows becomes strongly favored.

## Phase 4: Prefix Replacement Strategy

On Linux, worker isolation was expected to come from separate Proton compatdata prefixes.

On Windows, the equivalent problem becomes:

- how to isolate per-instance save/config/mod state

Candidate strategies:

- separate Windows user profiles
- per-instance working directories if Isaac honors them
- NTFS junction/symlink based redirection of save/config paths
- sandbox tools or lightweight VM approaches

This phase only matters if Phase 3 proves two live instances are possible or nearly possible.

Do not overdesign it up front.

## Phase 5: Native Speed-Control Feasibility Test

Windows is also attractive because timing hooks can target native Windows APIs directly.

First-pass tool:

- Cheat Engine speedhack

Questions:

- does Isaac tolerate speed scaling?
- does speed scaling increase useful environment throughput?
- does the mod/trainer protocol remain stable under higher game speed?

Test sequence:

1. Start one native Isaac instance.
2. Measure baseline steps/sec.
3. Apply modest speed increase such as `1.5x`.
4. Test `2x`.
5. Observe game stability, input behavior, reset behavior, and training throughput.

Success criteria:

- measurable wall-clock throughput gain
- no frequent desyncs or crashes
- reward and episode logic remain coherent

Failure modes:

- visual speed changes but logic does not help throughput
- game destabilizes at useful multipliers
- trainer or IPC becomes the bottleneck before game speed helps

If Cheat Engine proves the idea, a later custom Windows hook becomes worth considering.

## Phase 6: Decision Matrix

After Phases 1, 3, and 5, choose the platform path.

### Choose Windows if

- single-instance baseline works cleanly
- and either multi-instance works or speed-control works well

### Stay on Linux if

- Windows offers no multi-instance advantage
- and no better speed-control path
- and migration cost outweighs the runtime simplification

## Repo Changes If Windows Wins

### Immediate changes

- add Windows setup instructions
- add PowerShell install and launch scripts
- update `CLAUDE.md` environment assumptions
- keep core Python and Lua code cross-platform

### Near-term changes

- add Windows-specific multi-worker launcher
- add Windows-specific process isolation helpers if needed
- add runbook documentation for Isaac install, mod install, and launch order

### Deferred changes

- custom Windows speed hook implementation
- sandboxing or multi-user isolation tooling
- distributed rollout architecture

## Minimal Migration Sequence

The shortest useful path is:

1. bring up one native Isaac + Python training run on Windows
2. test whether two Isaac instances can coexist
3. test whether speedhack works on one instance
4. pick the better scaling path
5. only then port launch/orchestration code

This prevents spending time on Windows scripting before Windows proves its advantage.

## Risks

### Main risk

Windows may still have a hard single-instance limit for Isaac.

### Secondary risks

- save/config path isolation may be awkward
- Windows security tools may complicate injection-based speed tests
- developer ergonomics may be worse if the rest of your workflow stays on Linux

### Manageable risks

- launcher script rewrite
- path compatibility fixes
- mod install path differences

## Explicit Non-Goals

Not part of the initial Windows migration pass:

- rewriting the trainer
- redesigning the observation space
- switching RL libraries
- implementing a custom Windows speedhack immediately
- making Windows and Linux feature-identical from day one

## Recommendation

Treat Windows as a throughput validation branch, not a permanent ideological move.

The right next step is not "port everything to Windows."
The right next step is:

1. prove the existing single-instance loop works natively
2. test native multi-instance behavior
3. test native speed-control behavior
4. then decide whether full migration is worth it

If Windows clears either of the two scaling gates, it becomes the more pragmatic platform for this project.
