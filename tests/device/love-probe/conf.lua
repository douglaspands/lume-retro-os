-- Minimal LÖVE probe (game-experience-tuning 2.3): see main.lua.
function love.conf(t)
  t.identity = "lume-love-probe"
  t.window.title = "lume love probe"
  t.window.width = 640
  t.window.height = 480
  t.modules.joystick = false
  t.modules.physics = false
  t.modules.video = false
  t.modules.thread = false
end
