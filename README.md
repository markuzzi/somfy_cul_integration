<!-- GitHub Markdown Reference: https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github -->

# SOMFY RTS CUL

This software package provides a Home Assistant integration to connect a CUL wireless transceiver to control SOMFY RTS shades.

Only **Somfy RTS** (433.42 MHz) is supported. **Somfy io-homecontrol** (868 MHz, e.g. "Situo io" remotes) uses an encrypted, bidirectional protocol that cannot be controlled with a CUL; use a TaHoma or Connexoon box with the [Overkiz integration](https://www.home-assistant.io/integrations/overkiz/) instead. You need a CUL with a firmware supporting Somfy RTS (culfw or a-culfw, command `Ys`). A CUL for 433 MHz is recommended, 868 MHz sticks work with a reduced range.

Further information about the CUL: [Product page](http://busware.de/tiki-index.php?page=CUL), [firmware details](http://culfw.de/).

# Installation

![hacs badge](https://img.shields.io/badge/HACS-Default-orange)

SOMFY RTS CUL Integration can be installed via [HACS](https://hacs.xyz/), or by manually copying the [`somfy_cul`](https://github.com/markuzzi/somfy_cul_integration) directory to Home Assistant's `config/custom_components/` directory.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=markuzzi&repository=somfy_cul_integration)

## Configuration

The integration is configured in the UI. The YAML configuration of earlier versions is still supported, see below.

### Setup in the UI

1. Go to **Settings → Devices & services → Add integration** and search for **Somfy CUL**.
2. Select the serial port of the CUL stick (prefer the `/dev/serial/by-id/…` path, it does not change after a reboot) and the baud rate (38400 for most sticks).
3. Open the Somfy CUL entry and use **Add cover** to add a cover with its name, address, type, up and down time.

The **address** is the RTS channel the cover is paired with (1 to 6 hex digits, e.g. `ABCD`). For a new cover, choose any unused address and pair the cover afterwards with the `somfy_cul.prog_cover` action (see below). The **up and down time** in seconds are needed for setting positions; without them, the cover can only be opened, closed and stopped.

#### Inverse mode (awnings)

Home Assistant treats a position of 100 % as open and 0 % as closed. A shutter is open when it is moved up, but an awning is open when it is moved down (extended). Enable **Inverse mode** for awnings and similar covers:

| | Normal mode (shutter) | Inverse mode (awning) |
|---|---|---|
| Open | Up | Down (extend) |
| Close | Down | Up (retract) |
| 100 % | fully up | fully down (extended) |
| 0 % | fully down | fully up (retracted) |

The **up time** and **down time** always refer to the motor direction: for an awning in inverse mode, the down time is the time needed to extend it completely. The position in the state file (`current_pos`) is also stored in motor terms (100 = fully up), so it stays valid when inverse mode is switched on or off.

**Reverse direction** is a different option: it only swaps the Up and Down commands sent to the motor, e.g. if the motor was installed or programmed the other way round. Position and state are not affected, and the up and down times still refer to the real movement. Use inverse mode, not reverse direction, to get correct positions for an awning.

#### Remotes and sensors

With a CUL that can receive Somfy RTS frames, the integration notices the commands of Somfy remotes and sensors (e.g. Telis, Situo RTS, wind or sun sensors). This needs a 433 MHz CUL with an a-culfw firmware supporting Somfy RTS reception (a-culfw 1.26.09 with command `Ye`; not available on the CUL V4 and in 868 MHz firmware). Prebuilt firmware for all devices: [a-culfw-1.26.09-firmware.zip](https://github.com/meiser79/a-culfw/raw/somfy-rts-rx/a-culfw-1.26.09-firmware.zip) (source: branch [`somfy-rts-rx`](https://github.com/meiser79/a-culfw/tree/somfy-rts-rx) of the a-culfw fork; tested on a miniCUL 433 MHz). The integration enables the reception when it connects; firmware without reception ignores this.

- **Event**: every received command fires the event `somfy_cul_remote`, e.g. for automations triggered by a remote:

  ```yaml
  triggers:
    - trigger: event
      event_type: somfy_cul_remote
      event_data:
        address: "36A433"
        command: up
  ```

  The event data contains `address`, `command` (`my`, `up`, `down`, `my_up`, `my_down`, `up_down`, `my_up_down`, `prog`, `sun_flag`, `flag`), `command_code`, `rolling_code` and `rssi` (dBm, if the CUL reports it, e.g. after `X25`). A remote repeats its frame while the button is pressed; the repeats do not fire further events.
- **Linked remotes**: add the addresses of the remotes and sensors that are paired with the same motor to the **Remotes** of the cover. Their Up, Down and My (stop) commands then update the state and position of the cover, as if the command had been sent by Home Assistant. To add a remote, check **Search for a remote** in the cover dialog and submit it, then press a button on the remote within 30 seconds: the dialog returns with the remote selected and keeps your other entries. Remotes received recently are also offered in the list, e.g. press a button of the remote, then open the cover's **Reconfigure** dialog. My while the cover is not moving drives the motor to its favourite position, which the integration does not know; the position is then not changed.

Each cover can be changed later via its **Reconfigure** menu entry; the entry is reloaded automatically. Changing the address requires pairing the cover again. The **Configure** button of the entry contains the option to log received frames.

### YAML configuration

The YAML configuration of version 1.x keeps working: it is imported into the UI configuration at startup. The CUL is imported once; covers in YAML that do not exist yet are added at every startup, so covers can still be added in YAML. Covers that already exist are **not** changed by YAML anymore, change them in the UI instead. Home Assistant shows a repair message after the import; you can remove the YAML configuration to get rid of it.

```yaml
somfy_cul:
  cul_path: /dev/ttyAMA0
  baud_rate: 38400
  debug_rx: false  # optional, log received frames at debug level

cover:
  - platform: somfy_cul
    name: "Bad"
    address: "ABCD"
    up_time: 16
    down_time: 13
    device_class: shutter  # optional; "shutter:" is accepted as legacy key
    reversed: false        # optional
    inverted: false        # optional, inverse mode for awnings
    remotes:               # optional, linked remotes and sensors
      - "36A433"
```

### State file

Once created, the integration will create a file name `somfy_cover_state.yaml` in your `config` directory. It stores the `enc_key` and the `rolling_code` of each cover, using the cover's address as key. You can edit these values, e.g. to take over the values of another controller. Call `somfy_cul.reload_state` afterwards or restart Home Assistant.

```yaml
ABCD:
  current_pos: 100
  enc_key: 3
  rolling_code: 42
```

Do not delete this file and do not change the `address` of a cover: the cover only reacts to the address it was paired with and to rolling codes that are higher than the last one it received. Otherwise, you have to pair the cover again (see `somfy_cul.prog_cover`).

### Migrating from FHEM or another controller

To keep the pairing of your covers, take over the address, the encryption key and the rolling code of each cover:

| FHEM (`10_SOMFY`) | Home Assistant |
|-------------------|----------------|
| `address` (e.g. `11111F`) | `address` of the cover |
| `enc-key` (e.g. `A5`) | `enc_key` in `somfy_cover_state.yaml` |
| `rolling-code` (e.g. `012C`) | `rolling_code` in `somfy_cover_state.yaml` |

Numbers are read as decimal values, quoted strings as hex values. Hex values must be quoted, otherwise YAML may interpret them as decimal or octal numbers. Only the last digit of the encryption key is used. Disable the cover in FHEM before, since both controllers would use the same rolling codes.

```yaml
11111F:
  enc_key: "A5"
  rolling_code: "012C"
```

After a restart or `somfy_cul.reload_state`, the values are stored as decimal numbers.

### Upgrading

- **From 1.0.0 to 1.0.1 or later**: addresses with less than 6 hex digits are sent padded with leading zeros since version 1.0.1 (`ABCD` is sent as `00ABCD`). Version 1.0.0 sent them unpadded, which the CUL firmware interpreted as a different address. If a cover does not react after the upgrade, pair it again using `somfy_cul.prog_cover`.
- **From 1.0.x**: the state file used the entity id as key. Existing entries are migrated to the address automatically. Renaming an entity does no longer reset its rolling code.
- **From 1.x to 1.2.0**: the YAML configuration is imported into the UI, see above. Entity ids and the state file are kept. Each cover now has a device; empty devices left over from version 1.0.x can be deleted.

## Services

The integration registers several services to directly control or manage your SOMFY RTS covers.

| Service | Description |
|---------|-------------|
| `somfy_cul.prog_cover` | Put a cover into **programming mode** (needed to pair or re-pair a remote/cover). |
| `somfy_cul.open_cover` | Open the specified cover. |
| `somfy_cul.close_cover` | Close the specified cover. |
| `somfy_cul.stop_cover` | Stop the cover's movement immediately. |
| `somfy_cul.reload_state` | Reload the `somfy_cover_state.yaml` file from disk. Useful if you manually edited encryption keys or rolling codes. |
| `somfy_cul.reload_platform` | Reconnect to the CUL stick and restart the listener. |
| `somfy_cul.send_raw_command` | Send a raw command to the CUL and log the response. |

The cover services target one or more covers, for example:

```yaml
action: somfy_cul.prog_cover
target:
  entity_id: cover.bad
```

## Limitations

- **Position tracking**: Somfy RTS covers do not report their position. The integration calculates the position from `up_time` and `down_time`. Commands from other remotes or sensors (e.g. a wind sensor) are only noticed with a CUL firmware supporting Somfy RTS reception and if the remote is linked to the cover (see [Remotes and sensors](#remotes-and-sensors)). Commands that are not received, e.g. out of range, are missed.

# Contributing To The Project

![python badge](https://img.shields.io/badge/Made%20with-Python-orange)
![github contributors](https://img.shields.io/github/contributors/markuzzi/somfy_cul_integration?color=orange)
![last commit](https://img.shields.io/github/last-commit/markuzzi/somfy_cul_integration?color=orange)

There are several ways of contributing to this project, they include:

- Updating or improving the features
- Updating or improving the documentation
- Helping answer/fix any issues raised

# Licence

![github licence](https://img.shields.io/badge/Licence-MIT-orange)

This project uses the MIT Licence, for more details see the [licence](/doc/licence.md) document.

# Showing Your Appreciation

If you like this project, please give it a star on [GitHub](https://github.com/markuzzi/somfy_cul_integration) or consider becoming a [Sponsor](https://github.com/sponsors/markuzzi).
