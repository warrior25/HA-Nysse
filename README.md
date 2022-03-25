# HA-Nysse

## Introduction

Home Assistant integration to fetch public transport data for Tampere, Finland

## Installation

Copy the files to your `custom_components` folder.

## Setup

The integration can be set up from the frontend by searching for `Nysse`.

## Frontend example

Simple frontend example using [custom:html-template-card](https://github.com/PiotrMachowski/Home-Assistant-Lovelace-HTML-Jinja2-Template-card)
![Example](https://github.com/warrior25/HA-Nysse/raw/main/docs/frontend_example.jpg)

```yaml
type: custom:html-template-card
title: Hervantakeskus B
ignore_line_breaks: true
content: >
  {% for departure in states.sensor.nysse_0834.attributes.departures %}

  <div style="display:grid; grid-template-columns: 2fr 0.5fr; font-size: 20px">
  <div><ha-icon style="padding: 10px 10px 10px 10px" icon={{states.sensor.nysse_0834.attributes.icon}}></ha-icon>
  {{ departure.line}} - {{ departure.destination }}</div>
  <div style="text-align: right">{{ departure.time }} min</div></div>

  {% endfor %}
  ```