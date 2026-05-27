local capabilities = require "st.capabilities"
local ZigbeeDriver = require "st.zigbee"

local outlet = require "aqara_h2_outlet.common"

local driver_template = {
  supported_capabilities = {
    capabilities.switch,
    capabilities.powerMeter,
    capabilities.energyMeter,
    capabilities.voltageMeasurement,
    capabilities.currentMeasurement,
    capabilities.temperatureMeasurement,
    capabilities.refresh,
    capabilities.healthCheck,
  },
  lifecycle_handlers = outlet.lifecycle_handlers,
  capability_handlers = outlet.capability_handlers,
  zigbee_handlers = outlet.zigbee_handlers,
  current_config_version = 12,
  health_check = false,
}

local driver = ZigbeeDriver("aqara-h2-outlet-eu", driver_template)
driver:run()
