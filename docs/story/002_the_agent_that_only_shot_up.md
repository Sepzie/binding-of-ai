# Day 2: The Agent That Only Shot Up

## The First Long Run

The first real training run lasted long enough to feel consequential. Not a quick sanity check, not a toy loop with a few hundred timesteps, but hours. By the time it was interrupted, PPO had crossed 225,000 timesteps and the behavior was no longer random noise. The agent had found something.

What it found, unfortunately, was a cheap trick.

It learned to start the room and fire upward. In the narrow training setup we had given it, that was often enough. A single enemy, spawned in a predictable place, walking more or less toward the player. The policy wasn't good in any robust sense. It had just found the shortest path through a tiny slice of the problem space.

That turned the session into two separate investigations. First: what exactly survives a long run when training stops unexpectedly? Second: what exactly are we teaching the agent when the environment is this static?

## The Missing Checkpoints That Weren't Missing

The initial question was simple: if a long training session gets interrupted, is anything saved?

The answer looked like "no" for about thirty seconds. The repo-local `checkpoints/` directory was empty. That was bad news if true. But the numbers from the run said otherwise. At 225,280 timesteps, with checkpointing every 50,000 steps, there should have been multiple saves already. So either the callback wasn't running, or the files were going somewhere else.

They were going somewhere else.

The training script used relative paths: `../checkpoints` and `../logs`. Those were being resolved against the *process working directory*, not the repository root. Depending on how training was launched, checkpoints landed either inside the repo or one level above it. In this case they were sitting in `/home/sepehr/Projects/checkpoints`, not in the project.

Once found, the evidence was reassuring: periodic checkpoints at 50k, 100k, 150k, and 200k, plus interrupted and crash saves. The work hadn't vanished. It had just been filed in the wrong cabinet.

That led to a cleanup pass:
- checkpoint and log paths anchored to the repo root
- existing artifacts moved under the project
- resume improved so `--resume latest` and `--resume latest-compatible` could work without hunting down filenames manually
- checkpoint filenames switched to timestamp-first names so directory sorting finally matched chronology

The system stopped feeling temporary after that. It behaved more like infrastructure.

## The Double Save on Ctrl-C

Then there was the oddity: one `Ctrl-C`, two checkpoints.

Training would write both an `interrupted` checkpoint and a `crashed` checkpoint on shutdown. That looked like either a race or a lie. It turned out to be both.

The interrupt handler was trying to be helpful. It saved an interrupt checkpoint immediately, then closed the environment, then exited. The problem was that `model.learn()` was still active when the environment was closed out from under it. The env is backed by a TCP socket into the Isaac mod, so shutting it down mid-flight can surface a normal exception during the training loop. The generic crash handler saw that exception and did what it was told to do: save a crash checkpoint.

So one intentional interruption was being interpreted as:
- a graceful stop
- a crash caused by cleanup

The fix was not exotic. The signal handler stopped doing heavy work. On first `Ctrl-C`, it now just marks the run as interrupted and raises `KeyboardInterrupt`. The actual save happens in one place. Cleanup happens in one place. And if anything noisy happens during shutdown after the interrupt, the code preserves the interrupt checkpoint instead of fabricating a second crash checkpoint.

The important part wasn't just the bug fix. It was the boundary. Signal handlers should be minimal. Cleanup belongs in normal control flow.

## The Policy That Overfit a Single Angle

Once the training run was easy to trust, the agent behavior was easier to diagnose. The reward function already punished taking damage. That wasn't the issue. The issue was opportunity.

The agent was usually killing the enemy before it needed to learn anything subtle about positioning or dodging. A deterministic enemy spawn meant the room opened in roughly the same geometry every time. PPO didn't need to discover general combat. It only needed to discover one profitable reflex.

Shoot up.

We considered a more drastic curriculum trick: disable shooting entirely and reward survival so the agent would learn to juke first. That can work, but it teaches a different game. Useful maybe, but not the first correction to make.

The cleaner fix was to attack the overfitting source directly:
- randomize spawn positions
- keep it configurable
- leave hooks for future curricula without rewriting the mod again

That became a small but important design rule for the session: if we're touching environment behavior, make it tunable from config instead of hardcoding another experimental branch into Lua.

## Reusable Knobs

By the end of the pass, the training stack had new configuration surfaces:
- `phase.random_spawn_positions`
- `phase.spawn_radius_min`
- `phase.spawn_radius_max`
- `phase.disable_shooting`
- `reward.survival_bonus`

Only one of them was turned on immediately: random spawn for the current phase 1a config. The others exist as levers for the next experiments. Stronger enemies, survival-shaped reward, no-shoot curricula, different spawn envelopes. All of it can now be toggled through config and sent over the existing `configure` pathway from Python to the Lua mod.

That matters because experimentation is going to be the real work now. Not building the pipeline from scratch every day, but adjusting the curriculum without destabilizing the runtime.

## The Takeaway

The big lesson from this session was that "training progress" is not just model weights. It's operational confidence.

You need to know where checkpoints go. You need to know what happens on interruption. You need filenames that sort the way humans think. You need resume behavior that does the obvious thing. And you need training scenarios that don't accidentally teach the agent a brittle exploit and call it learning.

The agent that only shot up was not a failure. It was a mirror held up to the environment we built for it. The code was doing exactly what we asked. The next stage is asking better questions.
