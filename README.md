# HA-Nysse

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

## Introduction

Home Assistant integration to fetch public transport data for Tampere, Finland

## Installation

Copy the files to your `custom_components` folder or install as a HACS custom repository. More info on HACS [here](https://hacs.xyz/).

## Setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=nysse)

The integration can be set up from the frontend by searching for `Nysse`.

## Usage

Each station creates a sensor which contains data for departures from that station. Explanations for non self-explanatory attributes are listed below.

`realtime` - Indicates if the data is pulled from realtime vehicle monitoring or timetable data

## Frontend examples

Simple frontend examples using [custom:html-template-card](https://github.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card)

![Example](https://github.com/warrior25/HA-Nysse/raw/main/docs/frontend_example.jpg)

```yaml
type: custom:html-template-card
title: Keskustori D
ignore_line_breaks: true
content: >
  {% set departures = state_attr('sensor.keskustori_d_0015','departures')
  %} {% for i in range(0, departures | count, 1) %}

  <div style="display:grid; grid-template-columns: 2fr 1fr; font-size: 20px;
  padding: 10px 0px 0px 0px"> <div>{{ departures[i].line }} - {{
  departures[i].destination }}</div><div style="text-align: right">{% if
  departures[i].realtime %}<ha-icon style="color:green; padding: 0px 10px 0px
  0px" icon="mdi:signal-variant"></ha-icon>{% endif %} {% if
  departures[i].time_to_station | int < 21  %} {{departures[i].time_to_station}}
  min {% else %}{{departures[i].departure}}{% endif %}</div></div>

  {% endfor %}
```

![Service Alerts](https://github.com/warrior25/HA-Nysse/raw/main/docs/service_alerts.jpg)

```yaml
type: custom:html-template-card
ignore_line_breaks: true
title: Service Alerts
content: >
  {% set alerts = state_attr('sensor.nysse_service_alerts','alerts')
  %} {% for i in range(0, alerts | count, 1) %}

  <b>{{ alerts[i].start.strftime('%d.%m.%Y') }} - {{ alerts[i].end.strftime('%d.%m.%Y') }}</b><br>
  {{ alerts[i].description }}<br><br>

  {% endfor %}
```

## Advanced usage

### Combine data from multiple stops

```yaml
 - platform: template
    sensors:
      combined_stops:
        value_template: "{{ states('sensor.stop1') }}"
        attribute_templates:
          departures: >-
            {% set combined_data = state_attr('sensor.stop1', 'departures') + state_attr('sensor.stop2', 'departures') %}
            {{ combined_data | sort(attribute='time_to_station') }}
```

## Known issues / limitations

- Nysse API sometimes functions incorrectly. Errors logged with `Nysse API error` can be resolved on their own over time.
- Line icons are resolved from a hardcoded list of tram lines. If new tram lines are built, the list needs to be updated in `const.py`.
