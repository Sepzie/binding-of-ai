local Config = {}

Config.TCP_HOST = "127.0.0.1"
Config.TCP_PORT = 9999
Config.TCP_TIMEOUT = 0.1  -- short timeout (non-blocking design, only affects send backpressure)

-- How many game ticks between sending state / receiving actions
Config.FRAME_SKIP = 1

-- Room grid dimensions (standard room)
Config.GRID_WIDTH = 13
Config.GRID_HEIGHT = 7

-- Episode limits (0 = no limit; set via configure command)
Config.MAX_EPISODE_TICKS = 3000

-- Phase 1a defaults
Config.SPAWN_ENEMIES = true
Config.ENEMY_TYPE = 10      -- EntityType 10 = Gaper
Config.ENEMY_VARIANT = 0
Config.ENEMY_COUNT = 1
Config.ENEMY_COLLISION_DAMAGE = nil
Config.SPAWN_PICKUP_PENNY = false
Config.PICKUP_RANDOM_POSITION = false
Config.PICKUP_OFFSET_X = 180
Config.PICKUP_OFFSET_Y = 0
Config.PICKUP_RADIUS_MIN = 120
Config.PICKUP_RADIUS_MAX = 200
Config.TERMINAL_ON_PICKUP = false
Config.RANDOM_SPAWN_POSITIONS = false
Config.SPAWN_RADIUS_MIN = 80
Config.SPAWN_RADIUS_MAX = 160
Config.DISABLE_SHOOTING = false

return Config
