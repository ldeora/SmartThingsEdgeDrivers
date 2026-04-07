local capabilities = require "st.capabilities"
local ZigbeeDriver = require "st.zigbee"

local common = require "aqara_h2.common"

local driver_template = {
  supported_capabilities = {
    capabilities.switch,
    capabilities.button,
    capabilities.powerMeter,
    capabilities.energyMeter,
    capabilities.refresh,
    capabilities.healthCheck,
  },
  lifecycle_handlers = common.lifecycle_handlers,
  capability_handlers = common.capability_handlers,
  zigbee_handlers = common.zigbee_handlers,
  health_check = false,
  current_config_version = 8,
}

local driver = ZigbeeDriver("aqara-h2-wall-switches", driver_template)
driver:run()
