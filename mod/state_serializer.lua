local Config = require("config")

local StateSerializer = {}

-- Grid entity type constants
local GRID_WALL = 15
local GRID_ROCK = 2
local GRID_ROCKB = 3
local GRID_ROCKT = 4
local GRID_ROCK_ALT = 22
local GRID_PIT = 7
local GRID_SPIKES = 8
local GRID_SPIKES_ONOFF = 9
local GRID_POOP = 14
local GRID_TNT = 12
local GRID_FIREPLACE = 13
local GRID_SPIDERWEB = 10

-- Channel indices for the grid observation
StateSerializer.CHANNEL_WALLS = 1
StateSerializer.CHANNEL_OBSTACLES = 2
StateSerializer.CHANNEL_PITS = 3
StateSerializer.CHANNEL_PLAYER = 4
StateSerializer.CHANNEL_ENEMIES = 5
StateSerializer.CHANNEL_PROJECTILES = 6
StateSerializer.CHANNEL_PICKUPS = 7
StateSerializer.CHANNEL_DOORS = 8
StateSerializer.NUM_CHANNELS = 8

local function createGrid()
    local grid = {}
    for c = 1, StateSerializer.NUM_CHANNELS do
        grid[c] = {}
        for y = 1, Config.GRID_HEIGHT do
            grid[c][y] = {}
            for x = 1, Config.GRID_WIDTH do
                grid[c][y][x] = 0
            end
        end
    end
    return grid
end

local function worldToGrid(room, pos)
    local idx = room:GetClampedGridIndex(pos)
    local w = room:GetGridWidth()
    local x = (idx % w) + 1  -- 1-indexed
    local y = math.floor(idx / w) + 1
    -- Clamp to valid range
    x = math.max(1, math.min(x, Config.GRID_WIDTH))
    y = math.max(1, math.min(y, Config.GRID_HEIGHT))
    return x, y
end

local function isObstacle(gridType)
    return gridType == GRID_ROCK
        or gridType == GRID_ROCKB
        or gridType == GRID_ROCKT
        or gridType == GRID_ROCK_ALT
        or gridType == GRID_POOP
        or gridType == GRID_TNT
        or gridType == GRID_FIREPLACE
        or gridType == GRID_SPIDERWEB
end

function StateSerializer.serialize(game)
    local room = game:GetRoom()
    local level = game:GetLevel()
    local player = Isaac.GetPlayer(0)

    local grid = createGrid()

    -- Encode grid entities (walls, obstacles, pits)
    local gridWidth = room:GetGridWidth()
    local gridSize = room:GetGridSize()
    for idx = 0, gridSize - 1 do
        local gx = (idx % gridWidth) + 1
        local gy = math.floor(idx / gridWidth) + 1
        if gx >= 1 and gx <= Config.GRID_WIDTH and gy >= 1 and gy <= Config.GRID_HEIGHT then
            local gridEntity = room:GetGridEntity(idx)
            if gridEntity then
                local gType = gridEntity:GetType()
                if gType == GRID_WALL then
                    grid[StateSerializer.CHANNEL_WALLS][gy][gx] = 1
                elseif gType == GRID_PIT then
                    grid[StateSerializer.CHANNEL_PITS][gy][gx] = 1
                elseif gType == GRID_SPIKES or gType == GRID_SPIKES_ONOFF then
                    grid[StateSerializer.CHANNEL_OBSTACLES][gy][gx] = 1
                elseif isObstacle(gType) then
                    grid[StateSerializer.CHANNEL_OBSTACLES][gy][gx] = 1
                end
            end
        end
    end

    -- Player position on grid
    local px, py = worldToGrid(room, player.Position)
    grid[StateSerializer.CHANNEL_PLAYER][py][px] = 1

    -- Enemies, projectiles, pickups
    local enemies = {}
    local entities = Isaac.GetRoomEntities()
    for i = 1, #entities do
        local ent = entities[i]
        local ex, ey = worldToGrid(room, ent.Position)

        if ent:IsActiveEnemy(false) and not ent:IsDead() then
            -- Enemy channel: normalized HP (0-1)
            local maxHp = ent.MaxHitPoints
            local hp = ent.HitPoints
            local normalized = 1.0
            if maxHp > 0 then
                normalized = hp / maxHp
            end
            grid[StateSerializer.CHANNEL_ENEMIES][ey][ex] = math.max(
                grid[StateSerializer.CHANNEL_ENEMIES][ey][ex],
                normalized
            )
            table.insert(enemies, {
                type = ent.Type,
                variant = ent.Variant,
                hp = hp,
                max_hp = maxHp,
                position = {ent.Position.X, ent.Position.Y}
            })

        elseif ent.Type == 9 then
            -- Enemy projectile
            grid[StateSerializer.CHANNEL_PROJECTILES][ey][ex] = 1

        elseif ent.Type == 5 and ent.Variant ~= 100 then
            -- Pickup (not pedestal items)
            grid[StateSerializer.CHANNEL_PICKUPS][ey][ex] = 1
        end
    end

    -- Doors
    for slot = 0, 7 do
        local door = room:GetDoor(slot)
        if door then
            local dx, dy = worldToGrid(room, door.Position)
            if dx >= 1 and dx <= Config.GRID_WIDTH and dy >= 1 and dy <= Config.GRID_HEIGHT then
                local doorVal = 0.5  -- open
                if door:IsLocked() then
                    doorVal = 0.25
                end
                if room:IsClear() then
                    doorVal = 1.0
                end
                grid[StateSerializer.CHANNEL_DOORS][dy][dx] = doorVal
            end
        end
    end

    -- Player state vector
    local playerState = {
        hp_red = player:GetHearts(),
        hp_soul = player:GetSoulHearts(),
        hp_black = player:GetBlackHearts(),
        speed = player.MoveSpeed,
        damage = player.Damage,
        range = player.TearRange,
        fire_rate = player.MaxFireDelay,
        shot_speed = player.ShotSpeed,
        luck = player.Luck,
        num_bombs = player:GetNumBombs(),
        num_keys = player:GetNumKeys(),
        num_coins = player:GetNumCoins(),
        has_active_item = player:GetActiveItem() ~= 0,
        active_charge = player:GetActiveCharge(),
        position = {player.Position.X, player.Position.Y}
    }

    local state = {
        grid = grid,
        player = playerState,
        enemies = enemies,
        room_cleared = room:IsClear(),
        player_dead = player:IsDead(),
        tick = game:GetFrameCount(),
        enemy_count = #enemies
    }

    return state
end

return StateSerializer
