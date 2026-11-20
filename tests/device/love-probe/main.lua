-- LÖVE environment probe (game-experience-tuning 2.3).
-- Shows LANG, love.system.getPreferredLocales() and the local time on screen, writes them
-- (plus LANGUAGE and TZ) as key=value lines to /run/lume/love-probe.txt with plain Lua io
-- (love.filesystem cannot write there), and quits by itself after QUIT_AFTER seconds.
local OUT = "/run/lume/love-probe.txt"
local QUIT_AFTER = 3

local lines = {}
local elapsed = 0

local function env(name)
  local v = os.getenv(name)
  if v == nil or v == "" then return "n/a" end
  return v
end

local function locales()
  -- love.system.getPreferredLocales exists since LÖVE 11.4 (the image has 11.5)
  if not (love.system and love.system.getPreferredLocales) then return "n/a" end
  local ok, list = pcall(love.system.getPreferredLocales)
  if not ok or type(list) ~= "table" then return "n/a" end
  return table.concat(list, ",")
end

function love.load()
  lines = {
    "LANG=" .. env("LANG"),
    "LANGUAGE=" .. env("LANGUAGE"),
    "locales=" .. locales(),
    "TZ=" .. env("TZ"),
    "time=" .. os.date("%Y-%m-%d %H:%M"),
  }
  local f = io.open(OUT, "w")
  if f then
    f:write(table.concat(lines, "\n"), "\n")
    f:close()
  else
    lines[#lines + 1] = "write failed: " .. OUT
  end
end

function love.update(dt)
  elapsed = elapsed + dt
  if elapsed >= QUIT_AFTER then love.event.quit() end
end

function love.draw()
  love.graphics.printf(table.concat(lines, "\n"), 20, 20, 600)
end
