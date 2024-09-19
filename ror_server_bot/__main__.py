import asyncio
import logging
from pathlib import Path

import discord

from ror_server_bot.logging import configure_logging

from .config import parse_file
from .ror_bot import RoRClient

logger = logging.getLogger(__name__)


if __name__ == '__main__':
    config = parse_file(Path('config.yaml'))

    configure_logging(
        console_log_level=config.console_log_level,
        console_style=config.console_style,
        file_type=config.log_file_type,
        log_dir=config.log_folder,
    )

    def start() -> None:
        return

        class DiscordClient:
            pass

        intents = discord.Intents.default()
        intents.message_content = True

        client = DiscordClient(intents=intents)
        logger.warning(
            'Expect a slowdown when requesting guild information from Discord!'
        )
        client.run(client.config.discord_bot_token)

    clients = [RoRClient(client_cfg) for client_cfg in config.ror_clients]

    async def main() -> None:
        async with asyncio.TaskGroup() as tg:
            for client in clients:
                tg.create_task(client.start())

    asyncio.run(main())
