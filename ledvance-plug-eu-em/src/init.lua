local capabilities = require "st.capabilities"
local ZigbeeDriver = require "st.zigbee"

local plug = require "ledvance_plug_eu_em.common"

local driver_template = {
  supported_capabilities = {
    capabilities.switch,
    capabilities.powerMeter,
    capabilities.energyMeter,
    capabilities.voltageMeasurement,
    capabilities.currentMeasurement,
    capabilities.refresh,
    capabilities.healthCheck,
  },
  lifecycle_handlers = plug.lifecycle_handlers,
  capability_handlers = plug.capability_handlers,
  zigbee_handlers = plug.zigbee_handlers,
  current_config_version = 2,
  health_check = false,
}

local driver = ZigbeeDriver("ledvance-plug-eu-em", driver_template)
driver:run()
