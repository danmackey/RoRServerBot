import asyncio
import logging
from pathlib import Path

import discord

from ror_server_bot.logging import configure_logging

from .ror_bot import (
    Announcements,
    RoRClient,
    RoRClientConfig,
    ServerConfig,
    UserConfig,
)

logger = logging.getLogger(__name__)


if __name__ == '__main__':
    configure_logging(
        console_log_level='DEBUG',
        console_style='rich',
        file_type='log',
        log_dir=Path.cwd() / 'logs',
    )

    def start() -> None:
        class DiscordClient:
            pass

        intents = discord.Intents.default()
        intents.message_content = True

        client = DiscordClient(intents=intents)
        logger.warning(
            'Expect a slowdown when requesting guild information from Discord!'
        )
        client.run(client.config.discord_bot_token)

    config = RoRClientConfig(
        id='1',
        enabled=True,
        server=ServerConfig(
            host='10.90.1.64',
            port=12000,
            password=''
        ),
        user=UserConfig(
            token=''
        ),
        discord_channel_id=-1,
        announcements=Announcements(
            delay=10,
            enabled=False,
            messages=[
                'Hello, World!',
                'This is a test announcement!',
                'This is another test announcement!',
                'This is the last test announcement!'
            ]
        ),
        reconnection_interval=1,
        reconnection_tries=3,
    )

    client = RoRClient(config)

    async def main() -> None:
        async with client:
            while True:
                await asyncio.sleep(0.1)

    asyncio.run(main())
