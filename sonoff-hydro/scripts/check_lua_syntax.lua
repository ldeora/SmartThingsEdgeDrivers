-- Run with: texlua scripts/check_lua_syntax.lua src/init.lua src/sonoff_utils.lua
if #arg == 0 then
  io.stderr:write("usage: texlua scripts/check_lua_syntax.lua <lua files...>\n")
  os.exit(2)
end
for i = 1, #arg do
  local chunk, err = loadfile(arg[i])
  if not chunk then
    io.stderr:write(string.format("%s: %s\n", tostring(arg[i]), tostring(err)))
    os.exit(1)
  end
  print(string.format("%s: syntax ok", tostring(arg[i])))
end
