import asyncio
import logging
from typing import Callable

from .models import RoRClientConfig
from .ror_connection import RoRClientEvents, RoRConnection

logger = logging.getLogger(__name__)


class RoRClient:
    def __init__(self, client_config: RoRClientConfig) -> None:
        """Create a new RoRClient.

        :param client_config: The configuration to use for the client.
        """
        self.config = client_config

        self.server = RoRConnection(
            username=self.config.user.name,
            user_token=self.config.user.token,
            password=self.config.server.password,
            host=self.config.server.host,
            port=self.config.server.port,
        )

    async def __aenter__(self):
        for attempt in range(self.config.reconnection_tries):
            try:
                logger.info(
                    'Attempt %d/%d to connect to RoR server: %s',
                    attempt + 1,
                    self.config.reconnection_tries,
                    self.server.address
                )
                self.server = await self.server.__aenter__()
            except ConnectionRefusedError:
                logger.warning('Connection refused!')

                if attempt < self.config.reconnection_tries - 1:
                    logger.info(
                        'Waiting %.2f seconds before next attempt',
                        self.config.reconnection_interval
                    )
                    await asyncio.sleep(self.config.reconnection_interval)
            else:
                break

        if self.server.is_connected:
            logger.info('Connected to RoR server: %s', self.server.address)
        else:
            raise ConnectionError(
                f'Could not connect to RoR server {self.server.address} '
                f'after {self.config.reconnection_tries} attempts',
            )

        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.server.__aexit__(exc_type, exc, tb)

    def on(self, event: RoRClientEvents, listener: Callable | None = None):
        """Decorator to register an event handler on the event emitter.

        Example:
        ```
        @client.on(RoRClientEvents.USER_JOIN)
        def on_user_join(unique_id: int, user_info: UserInfo):
            print(f'User {user_info.name} joined the server')
        ```

        :param event: The event to register the handler on.
        :param listener: The listener to register.
        """
        return self.server.on(event, listener)

    def once(self, event: RoRClientEvents, listener: Callable | None = None):
        """Decorator to register a one-time event handler on the event
        emitter.

        Example:
        ```
        @client.once(RoRClientEvents.CHAT)
        def once_chat(unique_id: int, message: str):
            print(f'User {unique_id} sent a message: {message}')
        ```

        :param event: The event to register the handler on.
        :param listener: The listener to register.
        """
        return self.server.once(event, listener)
