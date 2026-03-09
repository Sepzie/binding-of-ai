# Day 1: The Protocol Wall

## The Setup

We had a working prototype. A Lua mod inside The Binding of Isaac talking to a Python training script over TCP. PPO agent, Gymnasium wrapper, the whole stack. State goes out, action comes in, 30 times a second. Simple lockstep protocol — Lua sends a game state, blocks until Python replies with an action. Clean, synchronous, easy to reason about.

It worked. For about 12,000 training steps we watched Isaac stumble around a room with a single Gaper, learning nothing yet but at least *running*. ~25 steps per second. Then Isaac died.

## The Death Screen Problem

When your character dies in Isaac, the game shows a death screen. A stats page, a sad jingle. And critically — the `MC_POST_UPDATE` callback stops firing. That's the 30hz game-logic tick that our entire protocol depends on. The Lua side goes silent. Python is sitting there, socket open, waiting for a state that will never come.

`TimeoutError. Connection timed out waiting for valid state after reset.`

The training script crashes. You restart it. If Isaac happens to still be on the death screen, same thing. The mod can't read the reset command because the only callback that reads commands just... stopped.

So we added `MC_POST_RENDER` — a rendering callback that fires even during death screens — as a secondary communication channel. It reads the reset command, triggers `Isaac.ExecuteCommand("restart")`, and the game comes back to life.

Fixed? Not quite.

## The Cascade

`MC_POST_RENDER` fires at the *rendering* framerate. 60+ FPS. Through Proton (Isaac runs via Wine/Proton on Linux), every socket operation has overhead. The game starts lagging — hard. Frames drop, input feels like molasses. We're doing socket I/O 60 times per second in what's essentially a compatibility layer.

We tried throttling — only check every 6th render frame. We tried making the receive non-blocking. Each fix created a new edge case. Stale actions piling up in the TCP buffer. Multiple reset commands queuing and causing restart cascades. The game resetting over and over because three reset commands were sitting in the buffer from when Python got impatient.

The fundamental issue: we were trying to run a synchronous protocol across two execution contexts (game logic vs. rendering) with different tick rates, different lifetimes, and a translation layer (Proton) adding latency to every syscall.

## The Redesign

Instead of patching, we stepped back and wrote a plan. The core insight was about *ownership*:

**Lua owns the game clock.** It always has. `MC_POST_UPDATE` fires when it fires. Death screens happen when they happen. Fighting this is fighting the engine.

So let Lua own everything that depends on the game clock:
- Terminal detection (death, room cleared, timeout)
- Immediate restart (no waiting for Python to send a reset command)
- Episode lifecycle (increment episode_id, track boundaries)
- Action latching (keep the last action if Python is slow)

And let Python own everything that *doesn't* need the game clock:
- Reward computation
- Policy inference
- Episode bookkeeping
- Synchronization (just wait for the next episode_id)

The protocol flips from request/response to a one-way stream. Lua sends observations tagged with `episode_id`, `terminal`, and `terminal_reason`. It never waits for a reply. It polls for actions non-blockingly — if there's one, latch it; if not, keep the old one. When the episode ends, Lua restarts *immediately* and starts streaming the next episode.

Python's `reset()` becomes trivial: wait until you see an `episode_id` higher than the last one. No drain logic. No retry loops. No special death-screen handling. The death screen doesn't even appear anymore because Lua restarts before it gets the chance.

## The Implementation

Two commits. One for Lua (non-blocking polling, terminal detection, action latching, episode tracking), one for Python (sync on episode_id, read terminal from state stream). The `MC_POST_RENDER` callback shrinks to just accepting connections and forwarding configure commands. All the bandaids — `_drain_and_receive`, reset retries, timeout-based state matching — gone.

First test after the rewrite: episodes transition cleanly. No lag. No crashes on death. The agent dies, the game restarts, Python picks up the new episode, training continues. The protocol is boring now. That's the point.

## The Takeaway

The lesson wasn't about TCP or Lua or game modding. It was about *ownership boundaries*. When two systems share a resource (the game clock, in this case), you can either synchronize them perfectly — which is fragile — or you can give one system clear ownership and let the other adapt. We spent hours patching a synchronous protocol to handle an inherently asynchronous situation. The fix was to stop pretending it was synchronous.

Sometimes the right abstraction isn't more clever code. It's admitting which side actually owns the clock.
