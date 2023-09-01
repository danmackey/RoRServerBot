import asyncio
import logging

import discord

from .ror_bot import RoRClient, RoRClientConfig

logger = logging.getLogger(__name__)

if __name__ == '__main__':
    def start():
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
        server=RoRClientConfig.ServerConfig(
            host='10.90.1.64',
            port=12000,
            password=''
        ),
        user=RoRClientConfig.UserConfig(
            token=''
        ),
        discord_channel_id=-1,
        announcements=RoRClientConfig.Announcements(),
        reconnection_interval=1,
        reconnection_tries=3,
    )

    client = RoRClient(config)

    async def main():
        async with client:
            while True:
                await asyncio.sleep(0.1)

    asyncio.run(main())
