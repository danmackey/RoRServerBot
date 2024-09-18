import asyncio
import logging
from pathlib import Path

import discord
import yaml

from ror_server_bot.logging import configure_logging

from .ror_bot import RoRClient, RoRClientConfig

logger = logging.getLogger(__name__)


if __name__ == '__main__':
    configure_logging(
        console_log_level='INFO',
        console_style='rich',
        file_type='log',
        log_dir=Path.cwd() / 'logs',
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
