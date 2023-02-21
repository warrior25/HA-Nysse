# HA-Nysse

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

## Introduction

Home Assistant integration to fetch public transport data for Tampere, Finland

## Installation

Copy the files to your `custom_components` folder or install as a HACS custom repository. More info on HACS [here](https://hacs.xyz/).

## Setup

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
  {% for departure in
  states.sensor.hervannan_kampus_a_0835.attributes.departures %}

  <div style="display:grid; grid-template-columns: 2fr 0.5fr; font-size: 20px">
  <div><ha-icon style="padding: 10px 10px 10px 10px" icon={{ departure.icon
  }}></ha-icon> {{ departure.line }} - {{ departure.destination }}</div><div
  style="text-align: right"> {% if departure.time_to_station | int < 26  %}
  {{departure.time_to_station }} min {% else %} {{departure.departure}} {% endif
  %}</div></div>

  {% endfor %}
  ```
