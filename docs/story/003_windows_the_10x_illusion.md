# Day 3: Windows and the 10x Illusion

## The Platform Flip

After two days of protocol surgery and curriculum tuning, we finally did the thing we had been circling: move runtime testing to Windows.

The Linux stack still worked, but it came with constant background complexity: Proton prefixes, Steam compat quirks, shell-script assumptions, and subtle timing weirdness when the game entered awkward states. The question was no longer "can Linux run it?" It was "is Linux still the fastest way to iterate?"

So the session started with a practical goal: get one clean Windows loop running end-to-end.

## First Contact: Environment Bring-Up

The first milestone was boring in the best way:
- create a Windows venv
- install dependencies
- verify CUDA availability
- install the mod
- run first training

CUDA looked "installed" at the driver level, but PyTorch landed as CPU-only on first install. That mismatch is easy to miss if you trust package defaults. Swapping to a CUDA wheel fixed it immediately, and torch confirmed the GPU.

Then came the classic platform trap: the mod was installed to `Documents\My Games\...\mods`, mods were enabled, and still nothing loaded.

The logs told the truth. This install was scanning Steam's game directory mods path:

`C:\Program Files (x86)\Steam\steamapps\common\The Binding of Isaac Rebirth\mods`

Once `IsaacRL` was installed there, the connection came up and training started.

The migration wasn't blocked by architecture. It was blocked by path assumptions.

## Windows Scripts, Finally

Linux had helper scripts. Windows had none.

So we added:
- `scripts/install_mod.ps1`
- `scripts/launch_training.ps1`

That moved setup from tribal command history into repeatable tooling:
- auto-detect mod locations
- choose junction or copy install mode
- default config handling
- venv-aware launch path

Small change, big leverage. A working system becomes a reusable system.

## Cheat Engine and the First Win

The speed-control experiment that had been painful on Linux worked quickly on Windows.

At first, speedhack over `1.0x` looked broken. Under `1.0x` worked, over `1.0x` seemed capped. The fix was disabling VSync in `options.ini` while the game was closed. After restart, speedhack took effect, and the jump was immediate:

- baseline around `~25 steps/sec`
- accelerated runs in the `~130-150 steps/sec` range

That alone justified the Windows validation branch.

## The 10x Illusion

Then came the misleading part.

Cheat Engine at `10x` did not produce `10x` training throughput. Not even close. Throughput rose, then sagged over time. At higher speed, Isaac sometimes appeared to stall in dumb behavior windows, reusing stale actions.

This is where the session got useful: we stopped reading the speedhack number and started reading the pipeline.

`steps/sec` is end-to-end:
- game simulation
- TCP transport
- Python env step
- policy inference
- PPO rollout/update overhead

So a 10x game clock can still yield a ~5x training gain if the rest of the loop becomes the bottleneck.

The number was not lying. We were asking it the wrong question.

## Resource Reality Check

Process inspection showed no catastrophic saturation:
- one active trainer connected to port `9999`
- Isaac and trainer together using roughly one CPU core equivalent during sampling
- GPU not maxed
- VRAM far from full

The slowdown pattern looked like coordination and update cadence limits, not raw hardware exhaustion.

In other words: we unlocked speed, but now optimization has moved up-stack.

## First Model, First Honest Result

The first full Windows run completed and produced a policy that could consistently clear the room. It was also strategically shallow: drift right, shoot left, repeat.

Not random anymore. Not robust yet.

That was the right ending for the day. The system is now fast enough to expose policy quality issues quickly, instead of spending hours proving infrastructure still boots.

## The Takeaway

Windows did not magically make RL easy. It removed enough friction that the real bottlenecks became visible:
- launch and install assumptions
- end-to-end throughput limits
- reward/curriculum shaping quality

And the biggest lesson from the speedhack pass was simple:

**Game speed is not training speed.**

The useful metric is still `steps/sec` over time, under controlled settings. Everything else is instrumentation noise or wishful thinking.

