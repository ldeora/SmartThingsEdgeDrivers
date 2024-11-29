local capabilities = require "st.capabilities"
local ZigbeeDriver = require "st.zigbee"
local clusters = require "st.zigbee.zcl.clusters"
local defaults = require "st.zigbee.defaults"
local device_management = require "st.zigbee.device_management"
local data_types = require "st.zigbee.data_types"
local utils = require "st.utils"
local log = require "log"

local MFG_CODE = 0x117C

-- Green: 0-35 µg/m³, Yellow: 35-120 µg/m³,. Red: >120 µg/m³
local PM25_UPPER_BOUNDS_TO_HEALTH_CONCERN = {
  { upper_bound = 15, value = "good" },
  { upper_bound = 35, value = "moderate" },
  { upper_bound = 55, value = "slightlyUnhealthy"},
  { upper_bound = 150, value = "unhealthy" },
  { upper_bound = 250, value = "veryUnhealthy" },
  { upper_bound = 0xFFFF, value = "hazardous" },
}

local TemperatureMeasurement = clusters.TemperatureMeasurement
local RelativeHumidity = clusters.RelativeHumidity

local Pm25ConcentrationMeasurement = {
  ID = 0x042A,
  attributes = {
    MeasuredValue = {
      ID = 0x0000,
      NAME = "MeasuredValue",
      base_type = data_types.SinglePrecisionFloat,
    },
    MinMeasuredValue = {
      ID = 0x0001,
      NAME = "MinMeasuredValue",
      base_type = data_types.SinglePrecisionFloat,
    },
    MaxMeasuredValue = {
      ID = 0x0002,
      NAME = "MaxMeasuredValue",
      base_type = data_types.SinglePrecisionFloat,
    },
    Tolerance = {
      ID = 0x0003,
      NAME = "Tolerance",
      base_type = data_types.SinglePrecisionFloat,
    },
  }
}

local TvocMeasurement = {
  ID = 0xFC7E,
  attributes = {
    MeasuredValue = {
      ID = 0x0000,
      NAME = "MeasuredValue",
      base_type = data_types.SinglePrecisionFloat,
    },
    MinMeasuredValue = {
      ID = 0x0001,
      NAME = "MinMeasuredValue",
      base_type = data_types.SinglePrecisionFloat,
    },
    MaxMeasuredValue = {
      ID = 0x0002,
      NAME = "MaxMeasuredValue",
      base_type = data_types.SinglePrecisionFloat,
    },
  }
}

local function added_handler(self, device)
  device:send(TemperatureMeasurement.attributes.MaxMeasuredValue:read(device))
  device:send(TemperatureMeasurement.attributes.MinMeasuredValue:read(device))

  device:send(device_management.attr_refresh(device, Pm25ConcentrationMeasurement.ID, Pm25ConcentrationMeasurement.attributes.MeasuredValue.ID))
  device:send(device_management.attr_refresh(device, TvocMeasurement.ID, TvocMeasurement.attributes.MeasuredValue.ID))
  device:send(device_management.attr_refresh(device, TemperatureMeasurement.ID, TemperatureMeasurement.attributes.MeasuredValue.ID))
  device:send(device_management.attr_refresh(device, RelativeHumidity.ID, RelativeHumidity.attributes.MeasuredValue.ID))
end

local function info_changed_handler(self, device, event, args)
  if args.old_st_store.preferences.tempMaxInterval ~= device.preferences.tempMaxInterval then
    log.info("Temperature Max Interval: " .. device.preferences.tempMaxInterval)
    device:send(TemperatureMeasurement.attributes.MeasuredValue:configure_reporting(device, 1, device.preferences.tempMaxInterval, 1))
  end

  if args.old_st_store.preferences.humMaxInterval ~= device.preferences.humMaxInterval then
    log.info("Humidity Max Interval: " .. device.preferences.humMaxInterval)
    device:send(RelativeHumidity.attributes.MeasuredValue:configure_reporting(device, 1, device.preferences.humMaxInterval, 1))
  end

  if args.old_st_store.preferences.pm25MaxInterval ~= device.preferences.pm25MaxInterval then
    log.info("PM2.5 Max Interval: " .. device.preferences.pm25MaxInterval)
    device:send(device_management.attr_config(device, {
      cluster = Pm25ConcentrationMeasurement.ID,
      attribute = Pm25ConcentrationMeasurement.attributes.MeasuredValue.ID,
      minimum_interval = 1,
      maximum_interval = device.preferences.pm25MaxInterval,
      data_type = Pm25ConcentrationMeasurement.attributes.MeasuredValue.base_type,
      reportable_change = data_types.SinglePrecisionFloat(0, 3, .25)
    }))
  end

  if args.old_st_store.preferences.tvocMaxInterval ~= device.preferences.tvocMaxInterval then
    log.info("TVOC Max Interval: " .. device.preferences.tvocMaxInterval)
    device:send(device_management.attr_config(device, {
      cluster = TvocMeasurement.ID,
      attribute = TvocMeasurement.attributes.MeasuredValue.ID,
      minimum_interval = 1,
      maximum_interval = device.preferences.tvocMaxInterval,
      data_type = TvocMeasurement.attributes.MeasuredValue.base_type,
      reportable_change = data_types.SinglePrecisionFloat(0, 3, .25),
      mfg_code = MFG_CODE
    }))
  end
end

local temperature_measurement_defaults = {
  MIN_TEMP = "MIN_TEMP",
  MAX_TEMP = "MAX_TEMP"
}
  
local temperature_measurement_min_max_attr_handler = function(minOrMax)
  return function(driver, device, value, zb_rx)
    local raw_temp = value.value
    local celc_temp = raw_temp / 100.0
    local temp_scale = "C"

    device:set_field(string.format("%s", minOrMax), celc_temp)

    local min = device:get_field(temperature_measurement_defaults.MIN_TEMP)
    local max = device:get_field(temperature_measurement_defaults.MAX_TEMP)

    if min ~= nil and max ~= nil then
      if min < max then
        device:emit_event_for_endpoint(zb_rx.address_header.src_endpoint.value, capabilities.temperatureMeasurement.temperatureRange({ value = { minimum = min, maximum = max }, unit = temp_scale }))
        device:set_field(temperature_measurement_defaults.MIN_TEMP, nil)
        device:set_field(temperature_measurement_defaults.MAX_TEMP, nil)
      else
        device.log.warn_with({hub_logs = true}, string.format("Device reported a min temperature %d that is not lower than the reported max temperature %d", min, max))
      end
    end
  end
end

local function custom_dust_attr_handler(driver, device, value, zb_rx)
  local dust_value = utils.round(value.value)

  local dust_value_int = math.floor(dust_value + 0.5) -- Convert float to integer by rounding

  local health_concern = "unhealthy"
  for _, candidate in ipairs(PM25_UPPER_BOUNDS_TO_HEALTH_CONCERN) do
      if dust_value_int < candidate.upper_bound then
          health_concern = candidate.value
          break
      end
  end

  device:emit_event(capabilities.fineDustSensor.fineDustLevel(dust_value))
  device:emit_event(capabilities.airQualityHealthConcern.airQualityHealthConcern(health_concern))
end

local function round_to(val, unit_val)
  local mult = 1 / unit_val
  if mult % 1 ~= 0 then
    error("unit_val should be a power of 10 (e.g., 0.1, 0.01, 0.001, etc.)")
  end
  return (utils.round(val * mult)) * unit_val
end

local function custom_tvoc_attr_handler(driver, device, value, zb_rx)
  local tvoc_ppm = value.value / 1000 -- Value is in ppb
  device:emit_event(capabilities.tvocMeasurement.tvocLevel({ value = round_to(tvoc_ppm, .001), unit = "ppm"}))
end

local ikea_vindstyrka_driver = {
  NAME = "IKEA VINDSTYRKA Handler",
  lifecycle_handlers = {
    added = added_handler,
    infoChanged = info_changed_handler
  },
  supported_capabilities = {
    capabilities.temperatureMeasurement,
    capabilities.relativeHumidityMeasurement,
    capabilities.fineDustSensor,
    capabilities.tvocMeasurement,
    capabilities.airQualityHealthConcern
  },
  zigbee_handlers = {
    global = {},
    cluster = {},
    attr = {
      [TemperatureMeasurement.ID] = {
        [TemperatureMeasurement.attributes.MinMeasuredValue.ID] = temperature_measurement_min_max_attr_handler(temperature_measurement_defaults.MIN_TEMP),
        [TemperatureMeasurement.attributes.MaxMeasuredValue.ID] = temperature_measurement_min_max_attr_handler(temperature_measurement_defaults.MAX_TEMP),
      },
      [Pm25ConcentrationMeasurement.ID] = {
        [Pm25ConcentrationMeasurement.attributes.MeasuredValue.ID] = custom_dust_attr_handler
      },
      [TvocMeasurement.ID] = {
        [TvocMeasurement.attributes.MeasuredValue.ID] = custom_tvoc_attr_handler
      }
    }
  },
  cluster_configurations = {
    [capabilities.fineDustSensor.ID] = {
      {
        cluster = Pm25ConcentrationMeasurement.ID,
        attribute = Pm25ConcentrationMeasurement.attributes.MeasuredValue.ID,
        minimum_interval = 1,
        maximum_interval = 30,
        reportable_change = data_types.SinglePrecisionFloat(0, 3, .25),
        data_type = Pm25ConcentrationMeasurement.attributes.MeasuredValue.base_type
      }
    },
    [capabilities.tvocMeasurement.ID] = {
      {
        cluster = TvocMeasurement.ID,
        attribute = TvocMeasurement.attributes.MeasuredValue.ID,
        minimum_interval = 1,
        maximum_interval = 30,
        reportable_change = data_types.SinglePrecisionFloat(0, 3, .25),
        data_type = TvocMeasurement.attributes.MeasuredValue.base_type,
        mfg_code = MFG_CODE,
      }
    }
  }
}
  
defaults.register_for_default_handlers(ikea_vindstyrka_driver, ikea_vindstyrka_driver.supported_capabilities)
local driver = ZigbeeDriver("ikea-vindstyrka-sensor", ikea_vindstyrka_driver)
driver:run()
