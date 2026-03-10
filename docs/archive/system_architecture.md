# System Architecture

Binding of Isaac RL training loop — Lua mod communicates with Python PPO trainer over TCP.

```mermaid
flowchart TB
    subgraph GAME["Binding of Isaac (30 Hz Game Loop)"]
        direction TB
        MC_POST_UPDATE["MC_POST_UPDATE<br/><i>every game tick</i>"]
        MC_INPUT_ACTION["MC_INPUT_ACTION<br/><i>input intercept</i>"]
        MC_POST_RENDER["MC_POST_RENDER<br/><i>menu/death polling</i>"]

        subgraph MOD["Lua Mod (mod/)"]
            direction TB
            MAIN["main.lua<br/><i>episode lifecycle</i>"]
            STATE_SER["state_serializer.lua<br/><i>8-ch grid + 14 player features</i>"]
            ACTION_INJ["action_injector.lua<br/><i>latch & inject actions</i>"]
            GAME_CTRL["game_control.lua<br/><i>spawn enemies, reset</i>"]
            CONFIG_LUA["config.lua<br/><i>FRAME_SKIP, TCP port</i>"]
        end

        MC_POST_UPDATE --> MAIN
        MC_INPUT_ACTION --> ACTION_INJ
        MC_POST_RENDER --> MAIN
    end

    subgraph TCP["TCP :9999 (JSON lines)"]
        direction LR
        STATE_MSG["State →<br/><i>grid, player, enemies,<br/>episode_id, terminal</i>"]
        ACTION_MSG["← Action<br/><i>move: 0-8, shoot: 0-4</i>"]
        CMD_MSG["← Commands<br/><i>configure, reset</i>"]
    end

    subgraph PYTHON["Python Training (python/)"]
        direction TB
        ENV["isaac_env.py<br/><b>IsaacEnv</b> (Gymnasium)<br/><i>step() blocks on receive</i>"]
        REWARD["reward.py<br/><b>RewardShaper</b><br/><i>damage, kills, death,<br/>survival, time penalty</i>"]
        NETWORK["network.py<br/><b>IsaacFeatureExtractor</b><br/><i>CNN(8→32→64→64) + MLP(14→64→64)<br/>→ FC(256)</i>"]

        subgraph SB3["Stable-Baselines3 PPO"]
            PPO_ALGO["PPO<br/><i>lr=3e-4, n_steps=2048<br/>batch=64, epochs=10</i>"]
            MONITOR["Monitor wrapper"]
        end

        subgraph OUTPUT["Outputs"]
            CKPT["checkpoints/<br/><i>timestamped .zip every 50k steps</i>"]
            TB["logs/PPO_N/<br/><i>TensorBoard events</i>"]
            WANDB["wandb<br/><i>run tracking, metrics,<br/>hyperparams (optional)</i>"]
            CONSOLE["Console logs<br/><i>EP summary, steps/sec,<br/>frames_dropped, latency</i>"]
        end

        CONFIG_YAML["configs/phase1a.yaml"]
    end

    %% Connections
    MAIN --> STATE_SER
    STATE_SER --> STATE_MSG
    STATE_MSG --> ENV
    ENV --> ACTION_MSG
    ACTION_MSG -->|"non-blocking poll"| MAIN
    CMD_MSG -->|"on connect"| MAIN
    MAIN --> ACTION_INJ
    MAIN --> GAME_CTRL

    ENV --> REWARD
    REWARD --> ENV
    ENV --> MONITOR
    MONITOR --> PPO_ALGO
    PPO_ALGO --> NETWORK
    PPO_ALGO --> CKPT
    PPO_ALGO --> TB
    PPO_ALGO --> WANDB
    ENV --> CONSOLE
    CONFIG_YAML --> ENV
    CONFIG_YAML --> PPO_ALGO

    style GAME fill:#1a1a2e,stroke:#e94560,color:#eee
    style MOD fill:#16213e,stroke:#e94560,color:#eee
    style TCP fill:#0f3460,stroke:#53a8b6,color:#eee
    style PYTHON fill:#1a1a2e,stroke:#53a8b6,color:#eee
    style SB3 fill:#16213e,stroke:#53a8b6,color:#eee
    style OUTPUT fill:#16213e,stroke:#53a8b6,color:#eee
    style STATE_MSG fill:#0f3460,stroke:#e94560,color:#eee
    style ACTION_MSG fill:#0f3460,stroke:#53a8b6,color:#eee
    style CMD_MSG fill:#0f3460,stroke:#53a8b6,color:#eee
```

## Key Dynamics

- **Lua owns the clock**: `MC_POST_UPDATE` fires at 30 Hz. State is serialized and pushed over TCP every `FRAME_SKIP` ticks.
- **Python blocks, Lua doesn't**: `step()` blocks on `_receive()`, but Lua's `pollAction()` is non-blocking (timeout=0). If Python is slow, Lua re-applies the last latched action.
- **Fire-and-forget actions**: Python sends actions without waiting for confirmation. Lua drains all buffered messages and latches the latest.
- **Episode sync via `episode_id`**: Lua increments on restart, Python spins in `_wait_for_new_episode()` until it sees a new ID.
- **Frame drop detection**: `episode_tick` (sent by Lua) lets Python detect gaps where states were missed.
