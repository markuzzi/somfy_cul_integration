<!-- GitHub Markdown Reference: https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github -->

# SOMFY RTS CUL

This software package provides a homeasstant integration to connect a CUL wireless transceiver to control SOMFY shades.

Further information about the CUL: [Product page](http://busware.de/tiki-index.php?page=CUL), [firmware details](http://culfw.de/).

# Installation

![hacs badge](https://img.shields.io/badge/HACS-Default-orange)

SOMFY RTS CUL Integration can be installed via [HACS](https://hacs.xyz/), or by manually copying the [`somfy_cul`](https://github.com/markuzzi/somfy_cul_integration) directory to Home Assistant's `config/custom_components/` directory.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=markuzzi&repository=somfy_cul_integration)

## Configuration

### CUL

Create the CUL hub by adding the following to your `configuration.yaml`.

```yaml
somfy_cul:
  cul_path: /dev/ttyAMA0
  baud_rate: 38400
  debug_rx: false  # optional, log received frames at debug level
```

### Covers / Shades

Add the following to your `configuration.yaml`. If you have multiple covers, you need to add multiple items.

```yaml
cover:
  - platform: somfy_cul
    name: "Bad"
    address: "ABCD"
    up_time: 16
    down_time: 13
```

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
| `address` (e.g. `11111F`) | `address` in `configuration.yaml` |
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
