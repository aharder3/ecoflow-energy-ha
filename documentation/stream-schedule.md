# Stream scheduled charge (app channel) - work in progress

Status: **experimental**. The encoder reproduces seven frames the vendor app
sent (Stream Ultra BK11 and Stream AC Pro BK31, Enhanced Mode). It has not been
sent to a device from this integration yet.

## What is known

Command `cmd_func 254 / cmd_id 17`, field `595`, published on the same
`/app/{user_id}/{sn}/thing/property/set` topic as the other app-channel writes.
The acknowledgement on `set_reply` carries only the field number (`595`) and
`1`; it says nothing about the plan itself.

| Field | Meaning (observed) |
|---|---|
| 2 | operation: 2 = change a plan, 3 = create a plan, 1 seen but unexplained |
| 3 | plan id (a plan kept its id across edits) |
| 4, 5, 8, 9, 12 | flags and constants, meaning unknown |
| 10 | window, `((end_slot << 16) \| start_slot) * 30`, slots of 30 minutes |
| 11.1 | `1` only when the source is "grid and solar" |
| 11.3 | per device: serial, target SoC in %, power in W |

The schedule is **not** reported back in any telemetry frame seen so far, so an
entity built on this would have to keep its own state.

## Open points

- Meaning of fields 4, 5, 8, 9, 12 and of operation 1.
- Delete / disable / enable of a plan: no frame captured yet.
- Weekdays and several plans per device: no frame captured yet.
- No live test from the integration yet.

## Sending a frame from Home Assistant (untested sketch)

`mqtt_client.send_proto_set(frame, wait=True)` is what the other proto writes
use. A service can build the frame with `stream_schedule.py` and hand it over;
the registration needs a two-line hook in `__init__.py` and is not part of this
change.
