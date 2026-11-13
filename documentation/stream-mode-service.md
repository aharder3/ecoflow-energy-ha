# Stream mode service (experimental)

`ecoflow_energy.set_stream_mode` switches the operating mode of a Stream
device over the app-channel MQTT connection (Enhanced Mode).

| `mode` | Wire frame | App name |
|---|---|---|
| `self_powered` | `106 { 1: 1 }` | Eigenstrommodus |
| `custom` | `106 { 2: 1 }` | Benutzerdefiniert |
| `ai` | `106 { 4: 1 }` | AI mode |

Scheduled plans (`send_stream_schedule`) belong to the custom mode. In the
vendor app, every plan edit was preceded by a switch to custom mode, so an
automation that sets a plan should switch to `custom` first. A plan is
probably not executed in the other modes; that has not been tested.

## Hook

Replace the hook described in `stream-schedule-service.md` with:

```python
async def async_setup(hass, config):
    from .services import async_register_services

    async_register_services(hass)
    return True
```

## Example

```yaml
action: ecoflow_energy.set_stream_mode
data:
  serial: BK11XXXXXXXXXXXX
  mode: custom
```

## Verified and not verified

- Verified live on a Stream Ultra and a Stream AC Pro: switching between the
  self-powered and the custom mode from Home Assistant. The app followed.
- Not verified: the AI mode sent from Home Assistant, a fourth mode (value 3
  has never been seen), whether one frame to one device switches both devices
  of a pair, and what happens to a stored plan when another mode is active.
- The mode is not reported back, so a switch made in the app is not
  reflected here.
