import asyncio
import logging
from pathlib import Path

import discord
import yaml

from ror_server_bot.logging import configure_logging

from .ror_bot import RoRClient
from .config import parse_file

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

    with open('bot.yaml') as f:
        config = RoRClientConfig.model_validate(yaml.safe_load(f))

    client = RoRClient(config)

    async def main() -> None:
        async with client:
            while True:
                await asyncio.sleep(0.1)

    asyncio.run(main())
