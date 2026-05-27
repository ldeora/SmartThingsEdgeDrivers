local cosock = require "cosock"
local socket = cosock.socket
local json = require "st.json"
local log = require "log"
local packet = require "tuya.packet"

local Client = {}
Client.__index = Client

local function now_string()
  return tostring(os.time())
end

local function compact_json(tbl)
  -- st.json.encode is already compact in Edge, but keep this isolated for easy replacement.
  return json.encode(tbl)
end

function Client.new(opts)
  local self = setmetatable({}, Client)
  self.host = opts.host
  self.port = opts.port or 6668
  self.device_id = opts.device_id
  self.local_key = opts.local_key
  self.seq = 1
  self.sock = nil
  self.timeout = opts.timeout or 3
  self.packet_debug = opts.packet_debug == true
  return self
end

function Client:close()
  if self.sock then
    pcall(function() self.sock:close() end)
  end
  self.sock = nil
end

function Client:connect()
  if self.sock then return true end
  local s = socket.tcp()
  s:settimeout(self.timeout)
  local ok, err = s:connect(self.host, self.port)
  if not ok then
    self.sock = nil
    return nil, err
  end
  self.sock = s
  return true
end

function Client:_next_seq()
  local seq = self.seq
  self.seq = self.seq + 1
  if self.seq > 0x7fffffff then self.seq = 1 end
  return seq
end

function Client:_send(cmd, payload_tbl)
  local plain = compact_json(payload_tbl)
  if self.packet_debug then log.debug(string.format("Tuya send cmd=%d json=%s", cmd, plain)) end
  local frame = packet.encode(self:_next_seq(), cmd, plain, self.local_key)
  local ok, err = self:connect()
  if not ok then return nil, err end
  local sent, send_err = self.sock:send(frame)
  if not sent then
    self:close()
    return nil, send_err
  end
  return true
end

function Client:_receive_one()
  local ok, err = self:connect()
  if not ok then return nil, err end

  local header, h_err, partial = self.sock:receive(16)
  if not header then
    self:close()
    return nil, h_err or "header receive failed"
  end

  local total, len_err = packet.expected_total_length(header)
  if not total then
    self:close()
    return nil, len_err or "invalid header"
  end

  local remaining = total - 16
  local rest = ""
  if remaining > 0 then
    local body, b_err = self.sock:receive(remaining)
    if not body then
      self:close()
      return nil, b_err or "body receive failed"
    end
    rest = body
  end

  local parsed, p_err = packet.parse_frame(header .. rest, self.local_key)
  if not parsed then return nil, p_err end

  if #parsed.payload == 0 then
    return { cmd = parsed.cmd, retcode = parsed.retcode, dps = nil, crc_ok = parsed.crc_ok }
  end

  local plain, dec_err = packet.decode_payload(parsed.payload, self.local_key)
  if not plain then return nil, dec_err end
  if self.packet_debug then log.debug("Tuya recv plain=" .. plain) end

  local ok_json, decoded = pcall(json.decode, plain)
  if not ok_json then return nil, "JSON decode failed: " .. tostring(decoded) .. " plain=" .. plain end
  decoded._tuya = { cmd = parsed.cmd, retcode = parsed.retcode, crc_ok = parsed.crc_ok }
  if decoded.data and decoded.data.dps and not decoded.dps then decoded.dps = decoded.data.dps end
  return decoded
end

function Client:status()
  local payload = {
    gwId = self.device_id,
    devId = self.device_id,
    uid = self.device_id,
    t = now_string(),
  }
  local ok, err = self:_send(packet.CMD_DP_QUERY, payload)
  if not ok then self:close(); return nil, err end
  local res, r_err = self:_receive_one()
  self:close()
  return res, r_err
end

function Client:heartbeat()
  local payload = { gwId = self.device_id, devId = self.device_id }
  return self:_send(packet.CMD_HEARTBEAT, payload)
end

function Client:set_dps(dps)
  local payload = {
    gwId = self.device_id,
    devId = self.device_id,
    uid = self.device_id,
    t = now_string(),
    dps = dps,
  }
  local ok, err = self:_send(packet.CMD_CONTROL, payload)
  if not ok then self:close(); return nil, err end
  local res, r_err = self:_receive_one()
  self:close()
  return res, r_err
end

function Client:receive_push()
  return self:_receive_one()
end

return Client
