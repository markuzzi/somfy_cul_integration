"""Constants for the Somfy CUL integration."""

from __future__ import annotations

from typing import Final

DOMAIN = "somfy_cul"

# Config flow
CONF_CUL_PATH: Final = "cul_path"  # /dev/ttyAMA0
CONF_BAUD_RATE: Final = "baud_rate"  # 38400
CONF_DEBUG_RX = "debug_rx"

CONF_NAME: Final = "name"
CONF_TYPE: Final = "shutter"
CONF_ADDRESS: Final = "address"
CONF_REVERSED: Final = "reversed"

ATTR_ENC_KEY: Final = "enc_key"
ATTR_ROLLING_CODE: Final = "rolling_code"
ATTR_UP_TIME: Final = "up_time"
ATTR_DOWN_TIME: Final = "down_time"
ATTR_CURRENT_POS: Final = "current_pos"

DATA_SOMFY_CUL = "somfy_cul_data"
DATA_RX_BUFFER = "rx_buffer"
DATA_RX_CALLBACK = "rx_callback"

MANUFACTURER = "Somfy"

SERVICE_PROG = "prog_cover"
SERVICE_OPEN = "open_cover"
SERVICE_CLOSE = "close_cover"
SERVICE_STOP = "stop_cover"
SERVICE_RELOAD = "reload_state"
SERVICE_RELOAD_PLATFORM = "reload_platform"
SERVICE_SEND_RAW_COMMAND = "send_raw_command"

SIGNAL_SOMFY_CUL_FRAME = "somfy_cul_frame"
