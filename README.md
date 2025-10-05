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
```

### Covers / Shades

Add the following to your `configuration.yaml`. If you have multiplt covers, you need to add multiple items.

```yaml
cover:
  - platform: somfy_cul
    name: "Bad"
    address: "ABCD"
    up_time: 16
    down_time: 13
```

Once created, the integration will create a file name `somfy_cover_state.yaml` in your `config` directory. In this file you can manipulate the `enc_keys` and the `rolling_codes` of the covers.

## Services

The integration registers several services to directly control or manage your SOMFY RTS covers.

| Service | Description | Example |
|---------|-------------|---------|
| `somfy_cul.prog_cover` | Put a cover into **programming mode** (needed to pair or re-pair a remote/cover). | ```yaml\nservice: somfy_cul.prog_cover\ndata:\n  entity_id: cover.somfy_cul_abcd\n``` |
| `somfy_cul.open_cover` | Open the specified cover. | ```yaml\nservice: somfy_cul.open_cover\ndata:\n  entity_id: cover.somfy_cul_abcd\n``` |
| `somfy_cul.close_cover` | Close the specified cover. | ```yaml\nservice: somfy_cul.close_cover\ndata:\n  entity_id: cover.somfy_cul_abcd\n``` |
| `somfy_cul.stop_cover` | Stop the cover’s movement immediately. | ```yaml\nservice: somfy_cul.stop_cover\ndata:\n  entity_id: cover.somfy_cul_abcd\n``` |
| `somfy_cul.reload_state` | Reload the `somfy_cover_state.yaml` file from disk. Useful if you manually edited encryption keys or rolling codes. | ```yaml\nservice: somfy_cul.reload_state\ndata:\n  entity_id: cover.somfy_cul_abcd\n``` |

All services require at least the `entity_id` of the target cover.

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
