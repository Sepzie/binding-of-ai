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

local function getSpawnRadius()
    local minRadius = Config.SPAWN_RADIUS_MIN or 80
    local maxRadius = Config.SPAWN_RADIUS_MAX or minRadius
    if maxRadius < minRadius then
        minRadius, maxRadius = maxRadius, minRadius
    end
    return minRadius, maxRadius
end

local function getRandomSpawnPos(room, centerPos)
    local minRadius, maxRadius = getSpawnRadius()
    local angle = math.random() * (math.pi * 2)
    local radius = minRadius
    if maxRadius > minRadius then
        radius = minRadius + math.random() * (maxRadius - minRadius)
    end

    local candidate = Vector(
        centerPos.X + math.cos(angle) * radius,
        centerPos.Y + math.sin(angle) * radius
    )
    return room:FindFreePickupSpawnPosition(candidate, 0, true)
end

function GameControl.spawnEnemies(game)
    local room = game:GetRoom()
    local centerPos = room:GetCenterPos()

    for i = 1, Config.ENEMY_COUNT do
        local spawnPos
        if Config.RANDOM_SPAWN_POSITIONS then
            spawnPos = getRandomSpawnPos(room, centerPos)
        else
            -- Offset enemies so they don't stack
            local offset = Vector(
                (i - 1) * 60 - (Config.ENEMY_COUNT - 1) * 30,
                0
            )
            spawnPos = Vector(centerPos.X + offset.X, centerPos.Y + offset.Y)
        end

        local enemy = Isaac.Spawn(
            Config.ENEMY_TYPE,
            Config.ENEMY_VARIANT,
            0,          -- subtype
            spawnPos,
            Vector(0, 0), -- velocity
            nil         -- spawner
        )
        if enemy and Config.ENEMY_COLLISION_DAMAGE ~= nil then
            enemy.CollisionDamage = Config.ENEMY_COLLISION_DAMAGE
        end
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
    if settings.enemy_collision_damage ~= nil then
        Config.ENEMY_COLLISION_DAMAGE = settings.enemy_collision_damage
    end
    if settings.random_spawn_positions ~= nil then
        Config.RANDOM_SPAWN_POSITIONS = settings.random_spawn_positions
    end
    if settings.spawn_radius_min then
        Config.SPAWN_RADIUS_MIN = settings.spawn_radius_min
    end
    if settings.spawn_radius_max then
        Config.SPAWN_RADIUS_MAX = settings.spawn_radius_max
    end
    if settings.frame_skip then
        Config.FRAME_SKIP = settings.frame_skip
    end
    if settings.spawn_enemies ~= nil then
        Config.SPAWN_ENEMIES = settings.spawn_enemies
    end
    if settings.max_episode_ticks then
        Config.MAX_EPISODE_TICKS = settings.max_episode_ticks
    end
end

return GameControl
