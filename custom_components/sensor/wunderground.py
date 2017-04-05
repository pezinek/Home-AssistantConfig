"""
Support for WUnderground weather service.

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.wunderground/
"""
from datetime import timedelta
import logging

import re
import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_MONITORED_CONDITIONS, CONF_API_KEY, TEMP_FAHRENHEIT, TEMP_CELSIUS,
    LENGTH_INCHES, LENGTH_KILOMETERS, LENGTH_MILES, LENGTH_FEET,
    STATE_UNKNOWN, ATTR_ATTRIBUTION, ATTR_FRIENDLY_NAME)
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv

_RESOURCE = 'http://api.wunderground.com/api/{}/{}/{}/q/'
_LOGGER = logging.getLogger(__name__)

CONF_ATTRIBUTION = "Data provided by the WUnderground weather service"
CONF_PWS_ID = 'pws_id'
CONF_LANG = 'lang'

DEFAULT_LANG = 'EN'

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=5)


# Helper classes for declaring sensor configurations

class WUSensorConfig(object):
    """WU Sensor Configuration.

    defines basic HA properties of the weather sensor and
    stores callbacks that can parse sensor values out of
    the json data received by WU API.
    """

    def __init__(self, friendly_name, feature, value,
                 unit_of_measurement=None, entity_picture=None,
                 icon="mdi:gauge", device_state_attributes=None):
        """Constructor.

        Args:
            friendly_name (string|func): Friendly name
            feature (string): WU feature. See:
                https://www.wunderground.com/weather/api/d/docs?d=data/index
            value (function(WUndergroundData)): callback that
                extracts desired value from WUndergroundData object
            unit_of_measurement (string): unit of meassurement
            entity_picture (string): value or callback returning
                URL of entity picture
            icon (string): icon name or URL
            device_state_attributes (dict): dictionary of attributes,
                or callable that returns it
        """
        self.friendly_name = friendly_name
        self.unit_of_measurement = unit_of_measurement
        self.feature = feature
        self.value = value
        self.entity_picture = entity_picture
        self.icon = icon
        self.device_state_attributes = device_state_attributes or {}


class WUCurrentConditionsSensorConfig(WUSensorConfig):
    """Helper for defining sensor configurations for current conditions."""

    def __init__(self, friendly_name, field, icon="mdi:gauge",
                 unit_of_measurement=None):
        """Constructor.

        Args:
            friendly_name (string|func): Friendly name of sensor
            field (string): Field name in the "current_observation"
                            dictionary.
            icon (string): icon name or URL, if None sensor
                           will use current weather symbol
            unit_of_measurement (string): unit of meassurement
        """
        super().__init__(
            friendly_name,
            "conditions",
            value=lambda wu: wu.data['current_observation'][field],
            icon=icon,
            unit_of_measurement=unit_of_measurement,
            entity_picture=lambda wu: wu.data['current_observation'][
                'icon_url'] if icon is None else None,
            device_state_attributes={
                'date': lambda wu: wu.data['current_observation'][
                    'observation_time']
            }
        )


class WUDailyTextForecastSensorConfig(WUSensorConfig):
    """Helper for defining sensor configurations for daily text forecasts."""

    def __init__(self, period, field):
        """Constructor.

        Args:
            period (int): forecast period number
            field (string):  field name to use as value
        """
        super().__init__(
            friendly_name=lambda wu: wu.data['forecast']['txt_forecast'][
                'forecastday'][period]['title'],
            feature='forecast',
            value=lambda wu: wu.data['forecast']['txt_forecast'][
                'forecastday'][period][field],
            entity_picture=lambda wu: wu.data['forecast']['txt_forecast'][
                'forecastday'][period]['icon_url'],
            device_state_attributes={
                'date': lambda wu: wu.data['forecast']['txt_forecast']['date']
            }
        )


class WUDailySimpleForecastSensorConfig(WUSensorConfig):
    """Helper for defining sensor configurations for daily simpleforecasts."""

    def __init__(self, friendly_name, period, field, wu_unit, ha_unit, icon=None):
        """Constructor.

        Args:
            period (int): forecast period number
            field (string): field name to use as value
            wu_unit (string): "fahrenheit", "celsius", "degrees" etc.
                 see the example json at:
        https://www.wunderground.com/weather/api/d/docs?d=data/forecast&MR=1
            ha_unit (string): coresponding unit in home assistant
            title (string): friendly_name of the sensor
        """
        super().__init__(
            friendly_name=friendly_name,
            feature='forecast',
            value=lambda wu: wu.data['forecast']['simpleforecast'][
                'forecastday'][period][field][wu_unit],
            unit_of_measurement=ha_unit,
            entity_picture=lambda wu: wu.data['forecast']['simpleforecast'][
                'forecastday'][period]['icon_url'] if not icon else None,
            icon=icon,
            device_state_attributes={
                'date': lambda wu: wu.data['forecast']['simpleforecast'][
                    'forecastday'][period]['date']['pretty']
            }
        )


class WUHourlyForecastSensorConfig(WUSensorConfig):
    """Helper for defining sensor configurations for hourly text forecasts."""

    def __init__(self, period, field):
        """Constructor.

        Args:
            period (int): forecast period number
            field (int): field name to use as value
        """
        super().__init__(
            friendly_name=lambda wu: "{} {}".format(
                wu.data['hourly_forecast'][period]['FCTTIME'][
                    'weekday_name_abbrev'],
                wu.data['hourly_forecast'][period]['FCTTIME'][
                    'civil']),
            feature='hourly',
            value=lambda wu: wu.data['hourly_forecast'][period][
                field],
            entity_picture=lambda wu: wu.data['hourly_forecast'][
                period]["icon_url"],
            device_state_attributes={
                'temp_c': lambda wu: wu.data['hourly_forecast'][
                    period]['temp']['metric'],
                'temp_f': lambda wu: wu.data['hourly_forecast'][
                    period]['temp']['english'],
                'dewpoint_c': lambda wu: wu.data['hourly_forecast'][
                    period]['dewpoint']['metric'],
                'dewpoint_f': lambda wu: wu.data['hourly_forecast'][
                    period]['dewpoint']['english'],
                'precip_prop': lambda wu: wu.data['hourly_forecast'][
                    period]['pop'],
                'sky': lambda wu: wu.data['hourly_forecast'][
                    period]['sky'],
                'precip_mm': lambda wu: wu.data['hourly_forecast'][
                    period]['qpf']['metric'],
                'precip_in': lambda wu: wu.data['hourly_forecast'][
                    period]['qpf']['english'],
                'humidity': lambda wu: wu.data['hourly_forecast'][
                    period]['humidity'],
                'wind_kph': lambda wu: wu.data['hourly_forecast'][
                    period]['wspd']['metric'],
                'wind_mph': lambda wu: wu.data['hourly_forecast'][
                    period]['wspd']['english'],
                'pressure_mb': lambda wu: wu.data['hourly_forecast'][
                    period]['mslp']['metric'],
                'pressure_inHg': lambda wu: wu.data['hourly_forecast'][
                    period]['mslp']['english'],
                'date': lambda wu: wu.data['hourly_forecast'][
                    period]['FCTTIME']['pretty'],
            },
        )


class WUAlmanacSensorConfig(WUSensorConfig):
    """Helper for defining field configurations for almanac sensors."""

    def __init__(self, friendly_name, field, value_type, wu_unit,
                 unit_of_measurement, icon):
        """Constructor.

        Args:
            friendly_name (string|func): Friendly name
            field (string): value name returned in 'almanac' dict
                            as returned by the WU API
            value_type (string):  "record" or "normal"
            wu_unit (string): unit name in WU API
            icon (string): icon name or URL
            unit_of_measurement (string): unit of meassurement
        """
        super().__init__(
            friendly_name=friendly_name,
            feature="almanac",
            value=lambda wu: wu.data['almanac'][field][value_type][wu_unit],
            unit_of_measurement=unit_of_measurement,
            icon=icon
        )


class WUAlertsSensorConfig(WUSensorConfig):
    """Helper for defining field configuration for alerts."""

    def __init__(self, friendly_name):
        """Constructor.

        Args:
            friendly_name (string|func): Friendly name
        """
        super().__init__(
            friendly_name=friendly_name,
            feature="alerts",
            value=lambda wu: len(wu.data['alerts']),
            icon=lambda wu: "mdi:alert-circle-outline" \
                if len(wu.data['alerts']) > 0 else \
                    "mdi:check-circle-outline",
            device_state_attributes=self._get_attributes
        )

    @staticmethod
    def _get_attributes(rest):

        attrs = {}

        if 'alerts' not in rest.data:
            return attrs

        alerts = rest.data['alerts']
        multiple_alerts = len(alerts) > 1
        for data in alerts:
            for alert in ALERTS_ATTRS:
                if data[alert]:
                    if multiple_alerts:
                        dkey = alert.capitalize() + '_' + data['type']
                    else:
                        dkey = alert.capitalize()
                    attrs[dkey] = data[alert]
        return attrs


# Declaration of supported WU sensors
# (see above helper classes for argument explanation)

SENSOR_TYPES = {
    'alerts': WUAlertsSensorConfig('Alerts'),
    'dewpoint_c': WUCurrentConditionsSensorConfig(
        'Dewpoint', 'dewpoint_c', 'mdi:water', TEMP_CELSIUS),
    'dewpoint_f': WUCurrentConditionsSensorConfig(
        'Dewpoint', 'dewpoint_f', 'mdi:water', TEMP_FAHRENHEIT),
    'dewpoint_string': WUCurrentConditionsSensorConfig(
        'Dewpoint Summary', 'dewpoint_string', 'mdi:water'),
    'feelslike_c': WUCurrentConditionsSensorConfig(
        'Feels Like', 'feelslike_c', 'mdi:thermometer', TEMP_CELSIUS),
    'feelslike_f': WUCurrentConditionsSensorConfig(
        'Feels Like', 'feelslike_f', 'mdi:thermometer', TEMP_FAHRENHEIT),
    'feelslike_string': WUCurrentConditionsSensorConfig(
        'Feels Like', 'feelslike_string', "mdi:thermometer"),
    'heat_index_c': WUCurrentConditionsSensorConfig(
        'Heat index', 'heat_index_c', "mdi:thermometer", TEMP_CELSIUS),
    'heat_index_f': WUCurrentConditionsSensorConfig(
        'Heat index', 'heat_index_f', "mdi:thermometer", TEMP_FAHRENHEIT),
    'heat_index_string': WUCurrentConditionsSensorConfig(
        'Heat Index Summary', 'heat_index_string', "mdi:thermometer"),
    'elevation': WUSensorConfig(
        'Elevation',
        'conditions',
        value=lambda wu: wu.data['current_observation'][
            'observation_location']['elevation'].split()[0],
        unit_of_measurement=LENGTH_FEET,
        icon="mdi:elevation-rise"),
    'location': WUSensorConfig(
        'Location',
        'conditions',
        value=lambda wu: wu.data['current_observation'][
            'display_location']['full'],
        icon="mdi:map-marker"),
    'observation_time': WUCurrentConditionsSensorConfig(
        'Observation Time', 'observation_time', "mdi:clock"),
    'precip_1hr_in': WUCurrentConditionsSensorConfig(
        'Precipitation 1hr', 'precip_1hr_in', "mdi:umbrella", LENGTH_INCHES),
    'precip_1hr_metric': WUCurrentConditionsSensorConfig(
        'Precipitation 1hr', 'precip_1hr_metric', "mdi:umbrella", 'mm'),
    'precip_1hr_string': WUCurrentConditionsSensorConfig(
        'Precipitation 1hr', 'precip_1hr_string', "mdi:umbrella"),
    'precip_today_in': WUCurrentConditionsSensorConfig(
        'Precipitation Today', 'precip_today_in', "mdi:umbrella",
        LENGTH_INCHES),
    'precip_today_metric': WUCurrentConditionsSensorConfig(
        'Precipitation Today', 'precip_today_metric', "mdi:umbrella", 'mm'),
    'precip_today_string': WUCurrentConditionsSensorConfig(
        'Precipitation Today', 'precip_today_string', "mdi:umbrella"),
    'pressure_in': WUCurrentConditionsSensorConfig(
        'Pressure', 'pressure_in', "mdi:gauge", 'inHg'),
    'pressure_mb': WUCurrentConditionsSensorConfig(
        'Pressure', 'pressure_mb', "mdi:gauge", 'mb'),
    'pressure_trend': WUCurrentConditionsSensorConfig(
        'Pressure Trend', 'pressure_trend', "mdi:gauge"),
    'relative_humidity': WUSensorConfig(
        'Relative Humidity',
        'conditions',
        value=lambda wu: int(wu.data['current_observation'][
            'relative_humidity'][:-1]),
        unit_of_measurement='%',
        icon="mdi:water-percent"),
    'station_id': WUCurrentConditionsSensorConfig(
        'Station ID', 'station_id', "mdi:home"),
    'solarradiation': WUCurrentConditionsSensorConfig(
        'Solar Radiation', 'solarradiation', "mdi:weather-sunny"),
    'temperature_string': WUCurrentConditionsSensorConfig(
        'Temperature Summary', 'temperature_string', "mdi:thermometer"),
    'temp_c': WUCurrentConditionsSensorConfig(
        'Temperature', 'temp_c', "mdi:thermometer", TEMP_CELSIUS),
    'temp_f': WUCurrentConditionsSensorConfig(
        'Temperature', 'temp_f', "mdi:thermometer", TEMP_FAHRENHEIT),
    'UV': WUCurrentConditionsSensorConfig(
        'UV', 'UV', "mdi:sunglasses"),
    'visibility_km': WUCurrentConditionsSensorConfig(
        'Visibility (km)', 'visibility_km', "mdi:eye", LENGTH_KILOMETERS),
    'visibility_mi': WUCurrentConditionsSensorConfig(
        'Visibility (miles)', 'visibility_mi', "mdi:eye", LENGTH_MILES),
    'weather': WUCurrentConditionsSensorConfig(
        'Weather Summary', 'weather', None),
    'wind_degrees': WUCurrentConditionsSensorConfig(
        'Wind Degrees', 'wind_degrees', "mdi:weather-windy"),
    'wind_dir': WUCurrentConditionsSensorConfig(
        'Wind Direction', 'wind_dir', "mdi:weather-windy"),
    'wind_gust_kph': WUCurrentConditionsSensorConfig(
        'Wind Gust', 'wind_gust_kph', "mdi:weather-windy", 'kph'),
    'wind_gust_mph': WUCurrentConditionsSensorConfig(
        'Wind Gust', 'wind_gust_mph', "mdi:weather-windy", 'mph'),
    'wind_kph': WUCurrentConditionsSensorConfig(
        'Wind Speed', 'wind_kph', "mdi:weather-windy", 'kph'),
    'wind_mph': WUCurrentConditionsSensorConfig(
        'Wind Speed', 'wind_mph', "mdi:weather-windy", 'mph'),
    'wind_string': WUCurrentConditionsSensorConfig(
        'Wind Summary', 'wind_string', "mdi:weather-windy"),
    'almanac_temp_high_record_c': WUAlmanacSensorConfig(
        lambda wu: 'High Temperature Record ({})'.format(
            wu.data['almanac']['temp_high']['recordyear']),
        'temp_high', 'record', 'C', TEMP_CELSIUS, 'mdi:thermometer'),
    'almanac_temp_high_record_f': WUAlmanacSensorConfig(
        lambda wu: 'High Temperature Record ({})'.format(
            wu.data['almanac']['temp_high']['recordyear']),
        'temp_high', 'record', 'F', TEMP_FAHRENHEIT, 'mdi:thermometer'),
    'almanac_temp_low_record_c': WUAlmanacSensorConfig(
        lambda wu: 'Low Temperature Record ({})'.format(
            wu.data['almanac']['temp_low']['recordyear']),
        'temp_low', 'record', 'C', TEMP_CELSIUS, 'mdi:thermometer'),
    'almanac_temp_low_record_f': WUAlmanacSensorConfig(
        lambda wu: 'Low Temperature Record ({})'.format(
            wu.data['almanac']['temp_low']['recordyear']),
        'temp_low', 'record', 'F', TEMP_FAHRENHEIT, 'mdi:thermometer'),
    'almanac_temp_low_normal_c': WUAlmanacSensorConfig(
        'Historic Average of Low Temperatures for Today',
        'temp_low', 'normal', 'C', TEMP_CELSIUS, 'mdi:thermometer'),
    'almanac_temp_low_normal_f': WUAlmanacSensorConfig(
        'Historic Average of Low Temperatures for Today',
        'temp_low', 'normal', 'F', TEMP_FAHRENHEIT, 'mdi:thermometer'),
    'almanac_temp_high_normal_c': WUAlmanacSensorConfig(
        'Historic Average of High Temperatures for Today',
        'temp_high', 'normal', 'C', TEMP_CELSIUS, "mdi:thermometer"),
    'almanac_temp_high_normal_f': WUAlmanacSensorConfig(
        'Historic Average of High Temperatures for Today',
        'temp_high', 'normal', 'F', TEMP_FAHRENHEIT, "mdi:thermometer"),
    'forecast_daily_1_text': WUDailyTextForecastSensorConfig(0, "fcttext"),
    'forecast_daily_1_text_metric': WUDailyTextForecastSensorConfig(
        0, "fcttext_metric"),
    'forecast_daily_2_text': WUDailyTextForecastSensorConfig(1, "fcttext"),
    'forecast_daily_2_text_metric': WUDailyTextForecastSensorConfig(
        1, "fcttext_metric"),
    'forecast_daily_3_text': WUDailyTextForecastSensorConfig(2, "fcttext"),
    'forecast_daily_3_text_metric': WUDailyTextForecastSensorConfig(
        2, "fcttext_metric"),
    'forecast_daily_4_text': WUDailyTextForecastSensorConfig(3, "fcttext"),
    'forecast_daily_4_text_metric': WUDailyTextForecastSensorConfig(
        3, "fcttext_metric"),
    'forecast_daily_5_text': WUDailyTextForecastSensorConfig(4, "fcttext"),
    'forecast_daily_5_text_metric': WUDailyTextForecastSensorConfig(
        4, "fcttext_metric"),
    'forecast_daily_6_text': WUDailyTextForecastSensorConfig(5, "fcttext"),
    'forecast_daily_6_text_metric': WUDailyTextForecastSensorConfig(
        5, "fcttext_metric"),
    'forecast_daily_7_text': WUDailyTextForecastSensorConfig(6, "fcttext"),
    'forecast_daily_7_text_metric': WUDailyTextForecastSensorConfig(
        6, "fcttext_metric"),
    'forecast_daily_8_text': WUDailyTextForecastSensorConfig(7, "fcttext"),
    'forecast_daily_8_text_metric': WUDailyTextForecastSensorConfig(
        7, "fcttext_metric"),
    'forecast_hourly_1_conditions': WUHourlyForecastSensorConfig(
        0, "condition"),
    'forecast_hourly_2_conditions': WUHourlyForecastSensorConfig(
        1, "condition"),
    'forecast_hourly_3_conditions': WUHourlyForecastSensorConfig(
        2, "condition"),
    'forecast_hourly_4_conditions': WUHourlyForecastSensorConfig(
        3, "condition"),
    'forecast_hourly_5_conditions': WUHourlyForecastSensorConfig(
        4, "condition"),
    'forecast_hourly_6_conditions': WUHourlyForecastSensorConfig(
        5, "condition"),
    'forecast_hourly_7_conditions': WUHourlyForecastSensorConfig(
        6, "condition"),
    'forecast_hourly_8_conditions': WUHourlyForecastSensorConfig(
        7, "condition"),
    'forecast_hourly_9_conditions': WUHourlyForecastSensorConfig(
        8, "condition"),
    'forecast_hourly_10_conditions': WUHourlyForecastSensorConfig(
        9, "condition"),
    'forecast_hourly_11_conditions': WUHourlyForecastSensorConfig(
        10, "condition"),
    'forecast_hourly_12_conditions': WUHourlyForecastSensorConfig(
        11, "condition"),
    'forecast_hourly_13_conditions': WUHourlyForecastSensorConfig(
        12, "condition"),
    'forecast_hourly_14_conditions': WUHourlyForecastSensorConfig(
        13, "condition"),
    'forecast_hourly_15_conditions': WUHourlyForecastSensorConfig(
        14, "condition"),
    'forecast_hourly_16_conditions': WUHourlyForecastSensorConfig(
        15, "condition"),
    'forecast_hourly_17_conditions': WUHourlyForecastSensorConfig(
        16, "condition"),
    'forecast_hourly_18_conditions': WUHourlyForecastSensorConfig(
        17, "condition"),
    'forecast_hourly_19_conditions': WUHourlyForecastSensorConfig(
        18, "condition"),
    'forecast_hourly_20_conditions': WUHourlyForecastSensorConfig(
        19, "condition"),
    'forecast_hourly_21_conditions': WUHourlyForecastSensorConfig(
        20, "condition"),
    'forecast_hourly_22_conditions': WUHourlyForecastSensorConfig(
        21, "condition"),
    'forecast_hourly_23_conditions': WUHourlyForecastSensorConfig(
        22, "condition"),
    'forecast_hourly_24_conditions': WUHourlyForecastSensorConfig(
        23, "condition"),
    'forecast_hourly_25_conditions': WUHourlyForecastSensorConfig(
        24, "condition"),
    'forecast_hourly_26_conditions': WUHourlyForecastSensorConfig(
        25, "condition"),
    'forecast_hourly_27_conditions': WUHourlyForecastSensorConfig(
        26, "condition"),
    'forecast_hourly_28_conditions': WUHourlyForecastSensorConfig(
        27, "condition"),
    'forecast_hourly_29_conditions': WUHourlyForecastSensorConfig(
        28, "condition"),
    'forecast_hourly_30_conditions': WUHourlyForecastSensorConfig(
        29, "condition"),
    'forecast_hourly_31_conditions': WUHourlyForecastSensorConfig(
        30, "condition"),
    'forecast_hourly_32_conditions': WUHourlyForecastSensorConfig(
        31, "condition"),
    'forecast_hourly_33_conditions': WUHourlyForecastSensorConfig(
        32, "condition"),
    'forecast_hourly_34_conditions': WUHourlyForecastSensorConfig(
        33, "condition"),
    'forecast_hourly_35_conditions': WUHourlyForecastSensorConfig(
        34, "condition"),
    'forecast_hourly_36_conditions': WUHourlyForecastSensorConfig(
        35, "condition"),
    'forecast_daily_1_high_temp_c': WUDailySimpleForecastSensorConfig(
        "High Temperature Today", 0, "high", "celsius", TEMP_CELSIUS,
        "mdi:thermometer"),
    'forecast_daily_2_high_temp_c': WUDailySimpleForecastSensorConfig(
        "High Temperature Tomorrow", 1, "high", "celsius", TEMP_CELSIUS,
        "mdi:thermometer"),
    'forecast_daily_3_high_temp_c': WUDailySimpleForecastSensorConfig(
        "High Temperature in 2 Days", 2, "high", "celsius", TEMP_CELSIUS,
        "mdi:thermometer"),
    'forecast_daily_4_high_temp_c': WUDailySimpleForecastSensorConfig(
        "High Temperature in 3 Days", 3, "high", "celsius", TEMP_CELSIUS,
        "mdi:thermometer"),
    'forecast_daily_1_high_temp_f': WUDailySimpleForecastSensorConfig(
        "High Temperature Today", 0, "high", "fahrenheit", TEMP_FAHRENHEIT,
        "mdi:thermometer"),
    'forecast_daily_2_high_temp_f': WUDailySimpleForecastSensorConfig(
        "High Temperature Tomorrow", 1, "high", "fahrenheit", TEMP_FAHRENHEIT,
        "mdi:thermometer"),
    'forecast_daily_3_high_temp_f': WUDailySimpleForecastSensorConfig(
        "High Temperature in 2 Days", 2, "high", "fahrenheit", TEMP_FAHRENHEIT,
        "mdi:thermometer"),
    'forecast_daily_4_high_temp_f': WUDailySimpleForecastSensorConfig(
        "High Temperature in 3 Days", 3, "high", "fahrenheit", TEMP_FAHRENHEIT,
        "mdi:thermometer"),
    'forecast_daily_1_low_temp_c': WUDailySimpleForecastSensorConfig(
        "Low Temperature Today", 0, "low", "celsius", TEMP_CELSIUS,
        "mdi:thermometer"),
    'forecast_daily_2_low_temp_c': WUDailySimpleForecastSensorConfig(
        "Low Temperature Tomorrow", 1, "low", "celsius", TEMP_CELSIUS,
        "mdi:thermometer"),
    'forecast_daily_3_low_temp_c': WUDailySimpleForecastSensorConfig(
        "Low Temperature in 2 Days", 2, "low", "celsius", TEMP_CELSIUS,
        "mdi:thermometer"),
    'forecast_daily_4_low_temp_c': WUDailySimpleForecastSensorConfig(
        "Low Temperature in 3 Days", 3, "low", "celsius", TEMP_CELSIUS,
        "mdi:thermometer"),
    'forecast_daily_1_low_temp_f': WUDailySimpleForecastSensorConfig(
        "Low Temperature Today", 0, "low", "fahrenheit", TEMP_FAHRENHEIT,
        "mdi:thermometer"),
    'forecast_daily_2_low_temp_f': WUDailySimpleForecastSensorConfig(
        "Low Temperature Tomorrow", 1, "low", "fahrenheit", TEMP_FAHRENHEIT,
        "mdi:thermometer"),
    'forecast_daily_3_low_temp_f': WUDailySimpleForecastSensorConfig(
        "Low Temperature in 2 Days", 2, "low", "fahrenheit", TEMP_FAHRENHEIT,
        "mdi:thermometer"),
    'forecast_daily_4_low_temp_f': WUDailySimpleForecastSensorConfig(
        "Low Temperature in 3 Days", 3, "low", "fahrenheit", TEMP_FAHRENHEIT,
        "mdi:thermometer"),
    'forecast_daily_1_max_wind_kph': WUDailySimpleForecastSensorConfig(
        "Max. Wind Today", 0, "maxwind", "kph", "kph", "mdi:weather-windy"),
    'forecast_daily_2_max_wind_kph': WUDailySimpleForecastSensorConfig(
        "Max. Wind Tomorrow", 1, "maxwind", "kph", "kph", "mdi:weather-windy"),
    'forecast_daily_3_max_wind_kph': WUDailySimpleForecastSensorConfig(
        "Max. Wind in 2 Days", 2, "maxwind", "kph", "kph",
        "mdi:weather-windy"),
    'forecast_daily_4_max_wind_kph': WUDailySimpleForecastSensorConfig(
        "Max. Wind in 3 Days", 3, "maxwind", "kph", "kph",
        "mdi:weather-windy"),
    'forecast_daily_1_max_wind_mph': WUDailySimpleForecastSensorConfig(
        "Max. Wind Today", 0, "maxwind", "mph", "mph",
        "mdi:weather-windy"),
    'forecast_daily_2_max_wind_mph': WUDailySimpleForecastSensorConfig(
        "Max. Wind Tomorrow", 1, "maxwind", "mph", "mph",
        "mdi:weather-windy"),
    'forecast_daily_3_max_wind_mph': WUDailySimpleForecastSensorConfig(
        "Max. Wind in 2 Days", 2, "maxwind", "mph", "mph",
        "mdi:weather-windy"),
    'forecast_daily_4_max_wind_mph': WUDailySimpleForecastSensorConfig(
        "Max. Wind in 3 Days", 3, "maxwind", "mph", "mph",
        "mdi:weather-windy"),
    'forecast_daily_1_avg_wind_kph': WUDailySimpleForecastSensorConfig(
        "Avg. Wind Today", 0, "avewind", "kph", "kph",
        "mdi:weather-windy"),
    'forecast_daily_2_avg_wind_kph': WUDailySimpleForecastSensorConfig(
        "Avg. Wind Tomorrow", 1, "avewind", "kph", "kph",
        "mdi:weather-windy"),
    'forecast_daily_3_avg_wind_kph': WUDailySimpleForecastSensorConfig(
        "Avg. Wind in 2 Days", 2, "avewind", "kph", "kph",
        "mdi:weather-windy"),
    'forecast_daily_4_avg_wind_kph': WUDailySimpleForecastSensorConfig(
        "Avg. Wind in 3 Days", 3, "avewind", "kph", "kph",
        "mdi:weather-windy"),
    'forecast_daily_1_avg_wind_mph': WUDailySimpleForecastSensorConfig(
        "Avg. Wind Today", 0, "avewind", "mph", "mph",
        "mdi:weather-windy"),
    'forecast_daily_2_avg_wind_mph': WUDailySimpleForecastSensorConfig(
        "Avg. Wind Tomorrow", 1, "avewind", "mph", "mph",
        "mdi:weather-windy"),
    'forecast_daily_3_avg_wind_mph': WUDailySimpleForecastSensorConfig(
        "Avg. Wind in 2 Days", 2, "avewind", "mph", "mph",
        "mdi:weather-windy"),
    'forecast_daily_4_avg_wind_mph': WUDailySimpleForecastSensorConfig(
        "Avg. Wind in 3 Days", 3, "avewind", "mph", "mph",
        "mdi:weather-windy"),
    'forecast_daily_1_precip_mm': WUDailySimpleForecastSensorConfig(
        "Precipitation Intensity Today", 0, 'qpf_allday', 'mm', 'mm',
        "mdi:umbrella"),
    'forecast_daily_2_precip_mm': WUDailySimpleForecastSensorConfig(
        "Precipitation Intensity Tomorrow", 1, 'qpf_allday', 'mm', 'mm',
        "mdi:umbrella"),
    'forecast_daily_3_precip_mm': WUDailySimpleForecastSensorConfig(
        "Precipitation Intensity in 2 Days", 2, 'qpf_allday', 'mm', 'mm',
        "mdi:umbrella"),
    'forecast_daily_4_precip_mm': WUDailySimpleForecastSensorConfig(
        "Precipitation Intensity in 3 Days", 3, 'qpf_allday', 'mm', 'mm',
        "mdi:umbrella"),
    'forecast_daily_1_precip_in': WUDailySimpleForecastSensorConfig(
        "Precipitation Intensity Today", 0, 'qpf_allday', 'in', LENGTH_INCHES,
        "mdi:umbrella"),
    'forecast_daily_2_precip_in': WUDailySimpleForecastSensorConfig(
        "Precipitation Intensity Tomorrow", 1, 'qpf_allday', 'in', LENGTH_INCHES,
        "mdi:umbrella"),
    'forecast_daily_3_precip_in': WUDailySimpleForecastSensorConfig(
        "Precipitation Intensity in 2 Days", 2, 'qpf_allday', 'in', LENGTH_INCHES,
        "mdi:umbrella"),
    'forecast_daily_4_precip_in': WUDailySimpleForecastSensorConfig(
        "Precipitation Intensity in 3 Days", 3, 'qpf_allday', 'in', LENGTH_INCHES,
        "mdi:umbrella"),
}

# Alert Attributes
ALERTS_ATTRS = [
    'date',
    'description',
    'expires',
    'message',
]

# Language Supported Codes
LANG_CODES = [
    'AF', 'AL', 'AR', 'HY', 'AZ', 'EU',
    'BY', 'BU', 'LI', 'MY', 'CA', 'CN',
    'TW', 'CR', 'CZ', 'DK', 'DV', 'NL',
    'EN', 'EO', 'ET', 'FA', 'FI', 'FR',
    'FC', 'GZ', 'DL', 'KA', 'GR', 'GU',
    'HT', 'IL', 'HI', 'HU', 'IS', 'IO',
    'ID', 'IR', 'IT', 'JP', 'JW', 'KM',
    'KR', 'KU', 'LA', 'LV', 'LT', 'ND',
    'MK', 'MT', 'GM', 'MI', 'MR', 'MN',
    'NO', 'OC', 'PS', 'GN', 'PL', 'BR',
    'PA', 'PU', 'RO', 'RU', 'SR', 'SK',
    'SL', 'SP', 'SI', 'SW', 'CH', 'TL',
    'TT', 'TH', 'UA', 'UZ', 'VU', 'CY',
    'SN', 'JI', 'YI',
]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_API_KEY): cv.string,
    vol.Optional(CONF_PWS_ID): cv.string,
    vol.Optional(CONF_LANG, default=DEFAULT_LANG):
    vol.All(vol.In(LANG_CODES)),
    vol.Required(CONF_MONITORED_CONDITIONS, default=[]):
    vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
})


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Setup the WUnderground sensor."""
    rest = WUndergroundData(hass,
                            config.get(CONF_API_KEY),
                            config.get(CONF_PWS_ID),
                            config.get(CONF_LANG))
    sensors = []
    for variable in config[CONF_MONITORED_CONDITIONS]:
        sensors.append(WUndergroundSensor(rest, variable))

    try:
        rest.update()
    except ValueError as err:
        _LOGGER.error("Received error from WUnderground: %s", err)
        return False

    add_devices(sensors)

    return True


class WUndergroundSensor(Entity):
    """Implementing the WUnderground sensor."""

    def __init__(self, rest, condition):
        """Initialize the sensor."""
        self.rest = rest
        self._condition = condition
        self.rest.request_feature(SENSOR_TYPES[condition].feature)

    def _cfg_expand(self, what, default=None):
        cfg = SENSOR_TYPES[self._condition]
        val = getattr(cfg, what)
        try:
            val = val(self.rest)
        except (KeyError, IndexError) as err:
            _LOGGER.error("Failed to parse response from WU API: %s", err)
            val = default
        except TypeError:
            pass # val was not callable - keep original value

        return val

    @property
    def name(self):
        """Return the name of the sensor."""
        return "PWS_" + self._condition

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._cfg_expand("value", STATE_UNKNOWN)

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        attrs = self._cfg_expand("device_state_attributes", {})
        for (attr, callback) in attrs.items():
            try:
                attrs[attr] = callback(self.rest)
            except TypeError:
                attrs[attr] = callback

        attrs[ATTR_ATTRIBUTION] = CONF_ATTRIBUTION
        attrs[ATTR_FRIENDLY_NAME] = self._cfg_expand("friendly_name")
        return attrs

    @property
    def icon(self):
        """Return icon."""
        return self._cfg_expand("icon", super().icon)

    @property
    def entity_picture(self):
        """Return the entity picture."""
        url = self._cfg_expand("entity_picture")
        if url is not None:
            return re.sub(r'^http://', 'https://', url, flags=re.IGNORECASE)

    @property
    def unit_of_measurement(self):
        """Return the units of measurement."""
        return self._cfg_expand("unit_of_measurement")

    def update(self):
        """Update current conditions."""
        self.rest.update()


class WUndergroundData(object):
    """Get data from WUnderground."""

    def __init__(self, hass, api_key, pws_id, lang):
        """Initialize the data object."""
        self._hass = hass
        self._api_key = api_key
        self._pws_id = pws_id
        self._lang = 'lang:{}'.format(lang)
        self._latitude = hass.config.latitude
        self._longitude = hass.config.longitude
        self._features = set()
        self.data = None

    def request_feature(self, feature):
        """Register feature to be fetched from WU API."""
        self._features.add(feature)

    def _build_url(self, baseurl=_RESOURCE):
        url = baseurl.format(
            self._api_key, "/".join(self._features), self._lang)
        if self._pws_id:
            url = url + 'pws:{}'.format(self._pws_id)
        else:
            url = url + '{},{}'.format(self._latitude, self._longitude)

        return url + '.json'

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Get the latest data from WUnderground."""
        try:
            result = requests.get(self._build_url(), timeout=10).json()
            if "error" in result['response']:
                raise ValueError(result['response']["error"]
                                 ["description"])
            else:
                self.data = result
        except ValueError as err:
            _LOGGER.error("Check WUnderground API %s", err.args)
            self.data = None
