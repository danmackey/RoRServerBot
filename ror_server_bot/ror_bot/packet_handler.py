import inspect

from pyee.asyncio import AsyncIOEventEmitter

from .enums import MessageType
from .models import Packet


class PacketHandler:
    def __init__(self, event_emitter: AsyncIOEventEmitter) -> None:
        """Create a new PacketHandler. This class is used to register
        event handlers on an EventEmitter. The event handlers are
        methods of this class that start with 'on_' or 'once_' and
        end with the name of the packet type.

        Methods must have the following signature:
        ```
        def on_hello(self, packet: Packet) -> None:
            ...
        def once_hello(self, packet: Packet) -> None:
            ...
        ```

        The method `on_hello` will be called when a `MessageType.HELLO`
        packet is received and the method `once_hello` will be called
        once when a `MessageType.HELLO` packet is received.

        :param event_emitter: The EventEmitter to register the packet
        handlers on. The event_emitter must have the wildcard option
        enabled. See `pymitter.EventEmitter` for more information.
        """
        for (name, method) in inspect.getmembers(self, inspect.ismethod):
            for prefix in ('on_', 'once_'):
                if name.startswith(prefix):
                    if name == prefix + 'packet':
                        event = 'packet'
                    else:
                        message_type = name[len(prefix):].upper()
                        if message_type not in MessageType._member_names_:
                            raise ValueError(
                                f'Invalid packet type: {message_type}'
                            )
                        event = f'packet.{message_type}'

                    parameters = inspect.signature(method).parameters

                    if len(parameters) != 1:
                        raise ValueError(
                            f'Invalid signature for "{name}". '
                            'Expected 2 parameters: self, packet',
                        )

                    (param_name, parameter), *_ = parameters.items()

                    if parameter.annotation != Packet:
                        raise ValueError(
                            f'Invalid signature for {name}. '
                            f'Expected "{param_name}" to be of type Packet'
                        )

                    if prefix == 'on_':
                        event_emitter.on(event, method)
                    elif prefix == 'once_':
                        event_emitter.once(event, method)


if __name__ == '__main__':
    class Test(PacketHandler):
        def __init__(self, event_emitter: AsyncIOEventEmitter) -> None:
            super().__init__(event_emitter)

        def on_hello(self, foo: Packet) -> None:
            print('hello', foo)

        def other_method(self) -> None:
            print('other_method')

    ee = AsyncIOEventEmitter()
    test = Test(ee)
    ee.emit('packet.*', Packet(command=MessageType.HELLO))
