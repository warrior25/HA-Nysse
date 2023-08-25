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

## Frontend example

Simple frontend example using [custom:html-template-card](https://github.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card)
![Example](https://github.com/warrior25/HA-Nysse/raw/main/docs/frontend_example.jpg)

```yaml
type: custom:html-template-card
title: Hervanan kampus A
ignore_line_breaks: true
content: >
  <div style="font-size:24px"><br>Hervannan kampus A</div>
  {% set departures = state_attr('sensor.hervannan_kampus_a_0835','departures') %}
  {% for i in range(0, departures | count, 1) %}

  <div style="display:grid; grid-template-columns: 2fr 1fr; font-size: 20px;
  padding: 10px 0px 0px 0px"> <div><ha-icon style="padding: 0px 10px 10px 0px;
  color:#da2128" icon="mdi:numeric-3-box"></ha-icon> {{ departures[i].destination
  }}</div><div style="text-align: right">{% if departures[i].realtime %}<ha-icon
  style="color:green; padding: 0px 10px 0px 0px"
  icon="mdi:signal-variant"></ha-icon>{% endif %} {% if
  departures[i].time_to_station | int < 21  %} {{departures[i].time_to_station}} min {%
  else %}{{departures[i].departure}}{% endif %}</div></div>

  {% endfor %}
  ```
