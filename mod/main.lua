local Config = require("config")
local TcpServer = require("tcp_server")
local StateSerializer = require("state_serializer")
local ActionInjector = require("action_injector")
local GameControl = require("game_control")

local mod = RegisterMod("IsaacRL", 1)

local server = TcpServer.new(Config.TCP_HOST, Config.TCP_PORT, Config.TCP_TIMEOUT)
local serverStarted = false
local tickCount = 0
local episodeActive = false

-- Initialize on game start
function mod:onGameStart(isContinue)
    if not serverStarted then
        serverStarted = server:start()
        ActionInjector.init()
    end
    GameControl.onGameStart()
    episodeActive = true
    tickCount = 0
    Isaac.ConsoleOutput("IsaacRL: Game started\n")
end

-- Handle new room
function mod:onNewRoom()
    GameControl.onNewRoom()
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

    tickCount = tickCount + 1

    -- Skip frames if configured
    if tickCount % Config.FRAME_SKIP ~= 0 then
        return
    end

    -- Don't send state during reset
    if GameControl.isResetting() then
        return
    end

    local game = Game()

    -- Serialize and send current state
    local state = StateSerializer.serialize(game)
    local sent = server:sendState(state)
    if not sent then
        return
    end

    -- Receive action from Python
    local message = server:receiveAction()
    if not message then
        return
    end

    -- Handle commands
    if message.command == "reset" then
        ActionInjector.reset()
        GameControl.resetEpisode()
        return
    elseif message.command == "configure" then
        if message.settings then
            GameControl.configure(message.settings)
        end
        return
    end

    -- Apply action
    if message.action then
        ActionInjector.setAction(message.action)
    end
end

-- Check for commands even when MC_POST_UPDATE isn't firing (death screen, menus)
function mod:onRender()
    if not serverStarted or not server.connected then
        return
    end
    -- Only act when onUpdate isn't running (player dead or resetting)
    local player = Isaac.GetPlayer(0)
    if player and not player:IsDead() and not GameControl.isResetting() then
        return  -- onUpdate handles it
    end

    -- Try to read a command (non-blocking)
    local message = server:receiveAction()
    if not message then
        return
    end

    if message.command == "reset" then
        Isaac.ConsoleOutput("IsaacRL: Reset from render callback\n")
        ActionInjector.reset()
        GameControl.resetEpisode()
    elseif message.command == "configure" then
        if message.settings then
            GameControl.configure(message.settings)
        end
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

Isaac.ConsoleOutput("IsaacRL: Mod loaded\n")
