# Day 8: The Wall Hugger

## The Network Gets a Promotion

After 1.2 million steps of flat-lining, the diagnosis was clear: the old network was too small. A 7×13 grid with 8 channels was being crushed through a 256-neuron bottleneck — 5,888 dimensions squeezed into 256. The critic couldn't model the value landscape with that little capacity, and noisy advantage estimates meant the policy was getting unreliable learning signals. Explained variance had been bouncing between 0.2 and 0.8 for over a million steps. The model wasn't going to think its way out of a straitjacket.

So we tripled it. CNN last layer from 64 to 128 filters. Player MLP from 64 to 128 neurons. Bottleneck from 256 to 512. Policy and value heads scaled proportionally. About 300K parameters total, up from 100K.

The question was whether to overshoot — build something that could handle enemies, projectiles, boss fights. The answer: moderate oversizing is fine in RL. You're not going to overfit when your data distribution shifts with every policy update. The danger zone is millions of parameters on small data. At 300K with millions of training steps, we had plenty of room.

Fresh training run. Old checkpoints incompatible. That was fine — the old model had plateaued anyway.

## What Isaac Learned First

The first 200K steps of the new model told a story nobody planned but everyone should have predicted.

Isaac learned about walls.

Not coins. Not pickups. Walls. The model's reward was -48 at the start and climbed to -43, and the entire improvement came from one thing: stop running into walls. The wall collision penalty was -0.05 per step spent colliding, and early random exploration meant hundreds of collision steps per episode. That was the loudest signal in the reward landscape — louder than the +5.0 for picking up a coin, because coins require you to *find* them first. Walls are everywhere. You hit them by accident. The gradient practically writes itself.

Watching the eval was comedy. Isaac would spawn, walk purposefully toward the center of the room, then pace back and forth in a careful pattern that kept him away from the walls. Perfect form. Zero coins collected. He looked like a nervous dad walking laps in a hospital waiting room.

The pickups_collected graph told the whole story: it started at 1.6 (random chance will land you on a coin occasionally) and *dropped* to 0.8 as the model learned. The model was actively getting worse at collecting coins because it was getting better at avoiding walls. It had learned that movement near walls is punished, and coins happen to spawn near walls sometimes, so the optimal strategy was... don't go near anything.

## The Critic's Report Card

Here's the thing though — the training metrics were actually beautiful. Explained variance climbed from 0 to 0.8. The critic, with its new capacity, was learning to predict returns accurately. Clip fraction settled at 0.02-0.04, well within healthy range. Value loss was declining. Entropy was *rising* — the policy was exploring more, not collapsing into a degenerate strategy.

The network wasn't broken. It was just learning the easy thing first.

This is a pattern in RL that doesn't get talked about enough: the order in which a model discovers reward signals matters. Dense, immediate penalties (wall collision every step) get picked up before sparse, delayed rewards (coin pickup requires navigation). A bigger network doesn't change this ordering — it just learns each signal faster and with more fidelity.

## The Curriculum Insight

The fix was obvious in retrospect: curriculum learning. Don't teach wall avoidance and coin collection simultaneously from scratch. Teach coins first — 100-200K steps of pure pickup training with no wall penalty. Let the model build a solid "coins are valuable, go get them" foundation. Then layer on the wall penalty. The model won't forget coins; it'll just learn to collect them without bouncing off walls along the way.

It's the difference between teaching someone to drive in a parking lot first, then on the road — versus dropping them on a highway and hoping they figure out both steering and traffic simultaneously.

The wall hugger wasn't a failure. It was the model telling us exactly what it needed: a lesson plan.
