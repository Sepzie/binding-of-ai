local Config = require("config")

local GameControl = {}

local waitingForReset = false
local resetFrame = 0
local RESET_DELAY = 5  -- frames to wait after reset command before sending state

function GameControl.resetEpisode()
    Isaac.ExecuteCommand("restart")
    waitingForReset = true
    resetFrame = 0
end

function GameControl.isResetting()
    return waitingForReset
end

function GameControl.onGameStart()
    if waitingForReset then
        resetFrame = Game():GetFrameCount()
    end
end

function GameControl.onNewRoom()
    if waitingForReset then
        local game = Game()
        -- Spawn configured enemies
        if Config.SPAWN_ENEMIES then
            GameControl.spawnEnemies(game)
        end
        waitingForReset = false
    end
end

function GameControl.spawnEnemies(game)
    local room = game:GetRoom()
    local centerPos = room:GetCenterPos()

    for i = 1, Config.ENEMY_COUNT do
        -- Offset enemies so they don't stack
        local offset = Vector(
            (i - 1) * 60 - (Config.ENEMY_COUNT - 1) * 30,
            0
        )
        local spawnPos = Vector(centerPos.X + offset.X, centerPos.Y + offset.Y)

        Isaac.Spawn(
            Config.ENEMY_TYPE,
            Config.ENEMY_VARIANT,
            0,          -- subtype
            spawnPos,
            Vector(0, 0), -- velocity
            nil         -- spawner
        )
    end
end

function GameControl.configure(settings)
    if settings.enemy_type then
        Config.ENEMY_TYPE = settings.enemy_type
    end
    if settings.enemy_variant then
        Config.ENEMY_VARIANT = settings.enemy_variant
    end
    if settings.enemy_count then
        Config.ENEMY_COUNT = settings.enemy_count
    end
    if settings.frame_skip then
        Config.FRAME_SKIP = settings.frame_skip
    end
    if settings.spawn_enemies ~= nil then
        Config.SPAWN_ENEMIES = settings.spawn_enemies
    end
end

return GameControl
