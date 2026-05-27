local aes = require "tuya.aes"

local packet = {}

packet.CMD_CONTROL = 7
packet.CMD_STATUS = 8
packet.CMD_HEARTBEAT = 9
packet.CMD_DP_QUERY = 10
packet.CMD_CONTROL_NEW = 13
packet.CMD_UPDATEDPS = 18

local PREFIX = 0x000055aa
local SUFFIX = 0x0000aa55
local VERSION_HEADER = "3.3" .. string.rep("\0", 12)

local crc_table
local function build_crc_table()
  local t = {}
  for i = 0, 255 do
    local c = i
    for _ = 1, 8 do
      if (c & 1) ~= 0 then
        c = (0xedb88320 ~ (c >> 1)) & 0xffffffff
      else
        c = (c >> 1) & 0xffffffff
      end
    end
    t[i] = c
  end
  return t
end

local function crc32(data)
  crc_table = crc_table or build_crc_table()
  local crc = 0xffffffff
  for i = 1, #data do
    local b = string.byte(data, i)
    crc = ((crc >> 8) ~ crc_table[(crc ~ b) & 0xff]) & 0xffffffff
  end
  return (~crc) & 0xffffffff
end

local function u32be(n)
  return string.char((n >> 24) & 0xff, (n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff)
end

local function read_u32be(s, pos)
  local a,b,c,d = string.byte(s, pos, pos + 3)
  return (((a << 24) | (b << 16) | (c << 8) | d) & 0xffffffff)
end

local function bytes_to_hex(s)
  return (s:gsub('.', function(c) return string.format('%02x', string.byte(c)) end))
end
packet.bytes_to_hex = bytes_to_hex

local function trim_to_json(s)
  local pos = s:find("{", 1, true)
  if pos and pos > 1 then return s:sub(pos) end
  return s
end

local function strip_clear_headers(payload)
  -- Tuya 3.3 inbound push frames may prefix ciphertext with
  --   "3.3" + 12 bytes of per-frame metadata
  -- not only the all-zero VERSION_HEADER used by some command frames.
  -- If removing the 15-byte prefix block-aligns the payload, try that first.
  if payload:sub(1, 3) == "3.3" and #payload > 15 and ((#payload - 15) % 16) == 0 then
    return payload:sub(16)
  end
  if payload:sub(1, 15) == VERSION_HEADER then
    return payload:sub(16)
  end
  if payload:sub(1, 3) == "3.3" and #payload > 24 and ((#payload - 24) % 16) == 0 then
    return payload:sub(25)
  end
  return payload
end

local function strip_decrypted_headers(plain)
  if plain:sub(1, 15) == VERSION_HEADER then
    plain = plain:sub(16)
  end
  if plain:sub(1, 3) == "3.3" and #plain >= 24 then
    plain = plain:sub(25)
  end
  return trim_to_json(plain)
end

function packet.encode(seq, cmd, plain_json, local_key)
  local payload = aes.encrypt_ecb(local_key, plain_json, true)
  if cmd ~= packet.CMD_DP_QUERY and cmd ~= packet.CMD_UPDATEDPS and cmd ~= packet.CMD_HEARTBEAT then
    payload = VERSION_HEADER .. payload
  end
  local length = #payload + 8 -- payload + CRC32 + suffix, matching TinyTuya 55AA framing
  local header = u32be(PREFIX) .. u32be(seq) .. u32be(cmd) .. u32be(length)
  local body = header .. payload
  return body .. u32be(crc32(body)) .. u32be(SUFFIX)
end

function packet.decode_payload(payload, local_key)
  if not payload or #payload == 0 then return nil, "empty payload" end

  local candidates = {
    payload,
    strip_clear_headers(payload),
  }

  for _, candidate in ipairs(candidates) do
    if candidate and #candidate > 0 and (#candidate % 16) == 0 then
      local ok, plain = pcall(aes.decrypt_ecb, local_key, candidate, true)
      if ok and plain then
        plain = strip_decrypted_headers(plain)
        if plain:sub(1, 1) == "{" then return plain end
      end
    end
  end

  -- Sometimes ACK/status can be clear JSON after frame parsing.
  local clear = strip_decrypted_headers(payload)
  if clear:sub(1, 1) == "{" then return clear end

  return nil, "unable to decrypt/parse payload hex=" .. bytes_to_hex(payload)
end

function packet.parse_frame(data, local_key)
  if #data < 24 then return nil, "frame too short" end
  local prefix = read_u32be(data, 1)
  if prefix ~= PREFIX then return nil, string.format("bad prefix 0x%08x", prefix) end
  local seq = read_u32be(data, 5)
  local cmd = read_u32be(data, 9)
  local length = read_u32be(data, 13)
  local total = 16 + length
  if #data < total then return nil, "incomplete frame" end
  local frame = data:sub(1, total)
  local crc_expected = read_u32be(frame, total - 7)
  local suffix = read_u32be(frame, total - 3)
  local crc_actual = crc32(frame:sub(1, total - 8))
  local retcode = read_u32be(frame, 17)
  local payload = frame:sub(21, total - 8)
  return {
    seq = seq,
    cmd = cmd,
    length = length,
    retcode = retcode,
    payload = payload,
    suffix = suffix,
    crc_ok = (crc_expected == crc_actual),
    raw = frame,
  }
end

function packet.expected_total_length(header16)
  if #header16 < 16 then return nil end
  local prefix = read_u32be(header16, 1)
  if prefix ~= PREFIX then return nil, "bad prefix" end
  local length = read_u32be(header16, 13)
  return 16 + length
end

return packet
