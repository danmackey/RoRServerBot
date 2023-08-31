import logging
import sys
from logging import handlers
from pathlib import Path

from devtools import PrettyFormat
from rich.logging import RichHandler

__version__ = '0.0.0'

RORNET_VERSION = 'RoRnet_2.44'

PROJECT_DIRECTORY = Path(__file__).parent

TRUCK_TO_NAME_FILE = Path('truck_to_name.json')


class PFormat(PrettyFormat):
    def _format_str_bytes(
        self,
        value: str | bytes,
        value_repr: str,
        indent_current: int,
        indent_new: int
    ) -> None:
        if isinstance(value, bytes):
            value = value.replace(b'\x00', b'')
        return super()._format_str_bytes(
            value,
            value_repr,
            indent_current,
            indent_new
        )


pformat = PFormat(indent_step=2)

stream_handler = logging.StreamHandler(sys.stdout)
file_handler = handlers.RotatingFileHandler(
    filename='ror_server_bot.log',
    mode='at',
    maxBytes=1024*1024*16,
    backupCount=5,
    encoding='utf-8'
)
rich_handler = RichHandler(
    omit_repeated_times=False,
    keywords=[
        '[CHAT]',
        '[EMIT]'
        '[GAME_CMD]',
        '[HEAD]',
        '[PCKT]',
        '[PRIV]',
        '[RECV]',
        '[SEND]',
    ]
)

stream_fmt = logging.Formatter(
    fmt='{asctime} | {levelname} | {filename}:{lineno} | {message}',
    style='{'
)
file_fmt = logging.Formatter(
    fmt='{asctime} | {levelname} | {filename}:{lineno} | {message}',
    style='{'
)
rich_fmt = logging.Formatter(fmt='{message}', style='{')

msec_fmt = '%s.%04d'
stream_fmt.default_msec_format = msec_fmt
file_fmt.default_msec_format = msec_fmt

stream_handler.setFormatter(stream_fmt)
stream_handler.setLevel(logging.INFO)
file_handler.setFormatter(file_fmt)
file_handler.setLevel(logging.DEBUG)
rich_handler.setFormatter(rich_fmt)
rich_handler.setLevel(logging.DEBUG)


logging.basicConfig(
    level=logging.DEBUG,
    handlers=[file_handler, rich_handler]
)
