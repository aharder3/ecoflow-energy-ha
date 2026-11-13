# Stream schedule service (experimental)

`ecoflow_energy.send_stream_schedule` writes one scheduled-charge plan to a
Stream device over the app-channel MQTT connection (Enhanced Mode). It builds
the frame described in `stream-schedule.md`.

## Hook

`schedule_service.py` is not wired up yet. Until it is, add this to
`custom_components/ecoflow_energy/__init__.py` (there is no `async_setup` yet):

```python
async def async_setup(hass, config):
    from .schedule_service import async_register_schedule_service

    async_register_schedule_service(hass)
    return True
```

## Example

Change plan 2 to 14:30-19:00, solar only, 95 % and 1050 W on both devices:

```yaml
action: ecoflow_energy.send_stream_schedule
data:
  serial: BK11XXXXXXXXXXXX
  serials:
    - BK11XXXXXXXXXXXX
    - BK31XXXXXXXXXXXX
  plan_id: 2
  start: "14:30"
  end: "19:00"
  source: solar          # or grid_and_solar
  soc: 95
  power: 1050
```

## Verified and not verified

- Verified live (Stream Ultra and Stream AC Pro): changing the window of an
  existing plan and switching its source between solar and grid and solar.
  The device acknowledged each frame and the app showed the change.
- Not verified: creating a plan, other plan ids, deleting or disabling a
  plan, weekdays, and sequence numbers in the range this service uses.
- The schedule is not reported back, so a plan changed in the app is not
  reflected here.
