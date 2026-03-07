local Config = {}

Config.TCP_HOST = "127.0.0.1"
Config.TCP_PORT = 9999
Config.TCP_TIMEOUT = 1.0  -- block until Python responds (keeps state in sync)

-- How many game ticks between sending state / receiving actions
Config.FRAME_SKIP = 1

-- Room grid dimensions (standard room)
Config.GRID_WIDTH = 13
Config.GRID_HEIGHT = 7

-- Phase 1a defaults
Config.SPAWN_ENEMIES = true
Config.ENEMY_TYPE = 10      -- EntityType 10 = Gaper
Config.ENEMY_VARIANT = 0
Config.ENEMY_COUNT = 1

return Config
