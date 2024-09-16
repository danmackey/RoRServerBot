import gzip
import logging
import sys
from pathlib import Path
from typing import Literal, overload

from pathvalidate import sanitize_filepath
from rich.logging import RichHandler

MSEC_FMT = '%s.%04d'

LogLevel = Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
ConsoleStyle = Literal['rich', 'basic']
FileType = Literal['gzip', 'log']


class GzipStreamHandler(logging.StreamHandler):
    """A handler class which writes logging records, appropriately
    formatted, to a gzip file."""

    def __init__(
        self,
        filename: Path,
        mode: str = 'wb',
        encoding: str = 'utf-8'
    ) -> None:
        """Creates a new GzipStreamHandler.

        :param filename: The name of the log file
        :param mode: The mode to open the file in, defaults to 'wb'
        :param encoding: The encoding to use, defaults to 'utf-8'
        """
        super().__init__()
        self.encoding = encoding
        self.gz_file = gzip.GzipFile(filename=filename, mode=mode)

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        self.gz_file.write(msg.encode(self.encoding))
        self.gz_file.write(b'\n')
        self.flush()

    def close(self) -> None:
        super().close()
        self.gz_file.close()


def get_log_handler(
    path: Path,
    formatter: logging.Formatter
) -> logging.FileHandler:
    """Get a logging handler that will write to a file in the given path.

    :param path: The path to the log file
    :param formatter: The formatter to use
    :return: A logging handler that will write to the log file
    """
    log_file = path / 'ror_server_bot.log'

    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)

    return file_handler


def get_gzip_handler(
    path: Path,
    formatter: logging.Formatter
) -> GzipStreamHandler:
    """Get a GzipStreamHandler that will write to a file in the given path.

    :param path: The path to the log file
    :param formatter: The formatter to use
    :return: A GzipStreamHandler
    """
    log_file_gz = path / 'ror_server_bot.log.gz'

    gz_handler = GzipStreamHandler(filename=log_file_gz)
    gz_handler.setFormatter(formatter)

    return gz_handler


@overload
def get_file_handler(
    path: Path,
    file_type: Literal['log']
) -> logging.FileHandler: ...


@overload
def get_file_handler(
    path: Path,
    file_type: Literal['gzip']
) -> GzipStreamHandler: ...


def get_file_handler(
    path: Path,
    file_type: FileType
) -> GzipStreamHandler | logging.FileHandler:
    """Get a handler that will write to a file in the given path.

    :param path: The path to the log file
    :param file_type: The type of file to write to, either 'gzip' or 'log'
    :return: A GzipStreamHandler
    """
    fmt = '{asctime} | {levelname} | {filename}:{lineno} | {message}'
    formatter = logging.Formatter(fmt=fmt, style='{')
    formatter.default_msec_format = MSEC_FMT

    match file_type:
        case 'gzip':
            return get_gzip_handler(path, formatter)
        case 'log':
            return get_log_handler(path, formatter)


def get_console_handler(
    style: ConsoleStyle,
    log_level: LogLevel
) -> logging.Handler:
    """Get a logging handler that will write to the console. The style
    parameter determines whether the handler will use the rich or basic
    logging format.

    :param style: The style of the logging handler, either 'rich' or
    'basic'
    :param log_level: The log level the handler will use
    :return: A logging handler that will write to the console
    """
    handler: logging.Handler
    if style == 'rich':
        handler = RichHandler(
            omit_repeated_times=False,
            keywords=[
                '[CHAT]',
                '[EMIT]'
                '[EVENT]'
                '[GCMD]',
                '[HEAD]',
                '[NETQ]',
                '[PCKT]',
                '[PRIV]',
                '[RECV]',
                '[STREAM]',
                '[SEND]',
                '[USER]',
            ]
        )
        formatter = logging.Formatter(fmt='{message}', style='{')
    else:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt='{asctime} | {levelname} | {filename}:{lineno} | {message}',
            style='{'
        )
        formatter.default_msec_format = MSEC_FMT

    handler.setFormatter(formatter)
    handler.setLevel(log_level)
    return handler


def configure_logging(
    console_log_level: LogLevel,
    console_style: ConsoleStyle,
    file_type: FileType,
    log_dir: Path | None = None,
) -> None:
    """Configure the logging module.

    :param console_log_level: The log level of the console logging
    :param console_style: The style of the console logging handler
    :param log_dir: The directory in which to store the log file. If
    None, no log file will be written
    """
    handlers = [get_console_handler(console_style, console_log_level)]

    if log_dir is not None:
        log_dir = sanitize_filepath(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        handlers.append(get_file_handler(log_dir, file_type))

    logging.basicConfig(level=logging.DEBUG, handlers=handlers)
