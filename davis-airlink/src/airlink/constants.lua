local constants = {}

constants.DRIVER_NAME = "Davis AirLink LAN"
constants.DRIVER_VERSION = "1.0.3"
constants.PROFILE_NAME = "davis-airlink"
constants.DNI_PREFIX = "davis-airlink:"

constants.MDNS_SERVICE_TYPE = "_airlink._tcp"
constants.MDNS_DOMAIN = "local"
constants.DEFAULT_PORT = 80
constants.DEFAULT_POLL_INTERVAL = 60
constants.MIN_POLL_INTERVAL = 60
constants.MAX_POLL_INTERVAL = 3600
constants.HTTP_TIMEOUT = 5
constants.OFFLINE_AFTER_FAILURES = 3

constants.FIELD_HOST = "airlink_host"
constants.FIELD_PORT = "airlink_port"
constants.FIELD_DID = "airlink_did"
constants.FIELD_NAME = "airlink_name"
constants.FIELD_POLL_TIMER = "airlink_poll_timer"
constants.FIELD_FAILURE_COUNT = "airlink_failure_count"
constants.FIELD_POLL_IN_PROGRESS = "airlink_poll_in_progress"
constants.FIELD_LAST_DATA = "airlink_last_data"
constants.FIELD_LAST_POLL_SOURCE = "airlink_last_poll_source"

constants.PM_UNIT = "μg/m^3"

constants.HEALTH_UNKNOWN = "unknown"
constants.HEALTH_GOOD = "good"
constants.HEALTH_MODERATE = "moderate"
constants.HEALTH_SLIGHTLY_UNHEALTHY = "slightlyUnhealthy"
constants.HEALTH_UNHEALTHY = "unhealthy"
constants.HEALTH_VERY_UNHEALTHY = "veryUnhealthy"
constants.HEALTH_HAZARDOUS = "hazardous"

constants.HEALTH_RANK = {
  [constants.HEALTH_UNKNOWN] = 0,
  [constants.HEALTH_GOOD] = 1,
  [constants.HEALTH_MODERATE] = 2,
  [constants.HEALTH_SLIGHTLY_UNHEALTHY] = 3,
  [constants.HEALTH_UNHEALTHY] = 4,
  [constants.HEALTH_VERY_UNHEALTHY] = 5,
  [constants.HEALTH_HAZARDOUS] = 6,
}

return constants
