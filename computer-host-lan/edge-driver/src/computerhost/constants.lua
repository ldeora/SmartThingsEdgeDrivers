local M = {}
M.DRIVER_NAME = "Computer Host LAN"
M.DRIVER_VERSION = "0.4.0-dev.1"
M.PROFILE_NAME = "computer-host-linux"
M.WINDOWS_PROFILE_NAME = "computer-host-windows"
M.BASIC_PROFILE_NAME = "computer-host"
M.PROTOCOL_NAME = "computer-host-agent"
M.PROTOCOL_VERSION = 2
M.PLATFORMS = {linux = true, windows = true}
function M.profile_for(platform)
  return platform == "windows" and M.WINDOWS_PROFILE_NAME or M.PROFILE_NAME
end
M.DNI_PREFIX = "computer-host:"
M.MDNS_SERVICE_TYPE = "_computerhost._tcp"
M.MDNS_DOMAIN = "local"
M.DEFAULT_PORT = 8765
M.HTTP_TIMEOUT = 4
M.DEFAULT_POLL_INTERVAL = 20
M.DEFAULT_TELEMETRY_INTERVAL = 60
M.REDISCOVERY_EVERY_FAILURES = 5
M.FIELD_HOST = "computerhost_host"
M.FIELD_PORT = "computerhost_port"
M.FIELD_UUID = "computerhost_uuid"
M.FIELD_NAME = "computerhost_name"
M.FIELD_PLATFORM = "computerhost_platform"
M.FIELD_MAC = "computerhost_mac"
M.FIELD_BROADCAST = "computerhost_broadcast"
M.FIELD_POWER_ACTIONS = "computerhost_actions"
M.FIELD_POLL_TIMER = "computerhost_poll_timer"
M.FIELD_METRICS_TIMER = "computerhost_metrics_timer"
M.FIELD_FAILURES = "computerhost_failures"
M.FIELD_HOST_FAILURES = "computerhost_host_failures"
M.FIELD_IN_PROGRESS = "computerhost_poll_busy"
M.FIELD_METRICS_BUSY = "computerhost_metrics_busy"
M.FIELD_LAST_OK = "computerhost_last_ok"
M.FIELD_LAST_BOOT = "computerhost_last_boot"
M.FIELD_LAST_STATUS = "computerhost_last_status"
M.FIELD_STATUS_PUBLISHED = "computerhost_status_published"
M.FIELD_LAST_SWITCH = "computerhost_last_switch"
M.FIELD_SWITCH_PUBLISHED = "computerhost_switch_published"
M.FIELD_PENDING_ACTION = "computerhost_pending_action"
M.FIELD_PENDING_AT = "computerhost_pending_at"
M.FIELD_LAST_TEMP = "computerhost_last_temperature"
M.FIELD_LAST_METRICS = "computerhost_metrics_values"
M.FIELD_PROFILE_UPDATE_SENT = "computerhost_advanced_profile_update_sent"
M.NAMESPACE = "oceancircle09600"
return M
