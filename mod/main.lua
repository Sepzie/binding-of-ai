local Config = require("config")
local TcpServer = require("tcp_server")
local StateSerializer = require("state_serializer")
local ActionInjector = require("action_injector")
local GameControl = require("game_control")

local mod = RegisterMod("IsaacRL", 1)

local server = TcpServer.new(Config.TCP_HOST, Config.TCP_PORT, Config.TCP_TIMEOUT)
local serverStarted = false
local tickCount = 0

-- Episode lifecycle (Lua owns)
local episodeId = 0
local episodeTick = 0
local hadEnemies = false
local episodeStartCoins = 0
local lastAction = {move = 0, shoot = 0}
local paused = false

-- Initialize on game start
function mod:onGameStart(isContinue)
    if not serverStarted then
        serverStarted = server:start()
        ActionInjector.init()
    end
    GameControl.onGameStart()

    -- New episode
    episodeId = episodeId + 1
    episodeTick = 0
    hadEnemies = false
    local player = Isaac.GetPlayer(0)
    episodeStartCoins = player and player:GetNumCoins() or 0
    lastAction = {move = 0, shoot = 0}
    ActionInjector.reset()

    Isaac.ConsoleOutput("IsaacRL[" .. Config.INSTANCE_ID .. "]: Episode " .. episodeId .. " started (port " .. Config.TCP_PORT .. ")\n")
end

-- Handle new room
function mod:onNewRoom()
    GameControl.onNewRoom()
end

-- Process a command message from Python
local function handleMessage(message)
    if message.command == "configure" then
        if message.settings then
            GameControl.configure(message.settings)
            if message.settings.disable_shooting ~= nil then
                ActionInjector.setDisableShooting(message.settings.disable_shooting)
            end
        end
    elseif message.command == "pause" then
        paused = true
    elseif message.command == "resume" then
        paused = false
    elseif message.command == "reset" then
        -- Manual/initial reset
        ActionInjector.reset()
        lastAction = {move = 0, shoot = 0}
        GameControl.resetEpisode()
    elseif message.action then
        lastAction = message.action
    end
end

-- Main update loop - runs every game tick (30/sec)
function mod:onUpdate()
    if not serverStarted then
        return
    end

    -- Try to accept a client if not connected
    if not server.connected then
        server:acceptClient()
        return
    end

    -- Poll for commands even when paused (to receive resume)
    if paused then
        while true do
            local message = server:pollAction()
            if not message then break end
            handleMessage(message)
        end
        return
    end

    tickCount = tickCount + 1

    -- Skip frames if configured
    if tickCount % Config.FRAME_SKIP ~= 0 then
        return
    end

    -- Don't send state during reset transition
    if GameControl.isResetting() then
        return
    end

    local game = Game()
    local player = Isaac.GetPlayer(0)
    if not player then
        return
    end

    episodeTick = episodeTick + 1

    -- Serialize state
    local state = StateSerializer.serialize(game)

    -- Track whether enemies have appeared this episode
    if state.enemy_count > 0 then
        hadEnemies = true
    end

    -- Detect terminal conditions
    local terminal = false
    local terminalReason = nil

    if player:IsDead() then
        terminal = true
        terminalReason = "death"
    elseif Config.TERMINAL_ON_PICKUP and player:GetNumCoins() > episodeStartCoins then
        terminal = true
        terminalReason = "pickup_collected"
    elseif hadEnemies and state.enemy_count == 0 then
        terminal = true
        terminalReason = "room_cleared"
    elseif Config.MAX_EPISODE_TICKS > 0 and episodeTick >= Config.MAX_EPISODE_TICKS then
        terminal = true
        terminalReason = "timeout"
    end

    -- Add episode metadata
    state.episode_id = episodeId
    state.episode_tick = episodeTick
    state.terminal = terminal
    state.terminal_reason = terminalReason

    -- Send state to Python
    local sent = server:sendState(state)
    if not sent then
        return
    end

    -- If terminal: restart immediately (Python will call reset, no action needed)
    if terminal then
        Isaac.ConsoleOutput("IsaacRL[" .. Config.INSTANCE_ID .. "]: Episode " .. episodeId .. " ended (" .. terminalReason .. ")\n")
        ActionInjector.reset()
        lastAction = {move = 0, shoot = 0}
        GameControl.resetEpisode()
        -- episodeId incremented in onGameStart
        return
    end

    -- Block until Python sends the next action (lock-step protocol).
    -- This prevents the game from running ahead of the agent, which would
    -- cause frame drops and corrupt the training signal.
    local message = server:waitForAction()
    if message then
        handleMessage(message)
        if GameControl.isResetting() then
            return
        end
    end

    -- Apply latched action
    ActionInjector.setAction(lastAction)
end

-- Accept connections and handle configure during non-gameplay states
function mod:onRender()
    if not serverStarted then
        return
    end

    if not server.connected then
        server:acceptClient()
        return
    end

    -- Only poll during non-gameplay states (death screen, menus, resetting)
    local player = Isaac.GetPlayer(0)
    if player and not player:IsDead() and not GameControl.isResetting() then
        return  -- onUpdate handles it
    end

    -- Drain buffered messages (configure, manual reset, start_run)
    while true do
        local message = server:pollAction()
        if not message then break end
        handleMessage(message)
    end
end

-- Input interception callback
function mod:onInputAction(entity, inputHook, buttonAction)
    if not server.connected then
        return nil
    end
    return ActionInjector.onInputAction(nil, entity, inputHook, buttonAction)
end

-- Register callbacks
mod:AddCallback(ModCallbacks.MC_POST_GAME_STARTED, mod.onGameStart)
mod:AddCallback(ModCallbacks.MC_POST_NEW_ROOM, mod.onNewRoom)
mod:AddCallback(ModCallbacks.MC_POST_UPDATE, mod.onUpdate)
mod:AddCallback(ModCallbacks.MC_POST_RENDER, mod.onRender)
mod:AddCallback(ModCallbacks.MC_INPUT_ACTION, mod.onInputAction)

Isaac.ConsoleOutput("IsaacRL[" .. Config.INSTANCE_ID .. "]: Mod loaded (port " .. Config.TCP_PORT .. ")\n")
