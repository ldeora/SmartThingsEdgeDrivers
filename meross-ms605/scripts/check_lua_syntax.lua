local filename = arg[1] or "src/init.lua"
local chunk, err = loadfile(filename)
if not chunk then
  io.stderr:write(string.format("%s: %s\n", filename, tostring(err)))
  os.exit(1)
end
print(string.format("%s: syntax ok", filename))
