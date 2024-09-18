from collections.abc import Callable
from enum import Enum
from functools import update_wrapper
from typing import Any


class singledispatchmethod:  # noqa: N801
    """Descriptor for creating single-dispatch methods. This is a
    simplified version of the `functools.singledispatchmethod` decorator
    that allows for dispatching based on the enum value of the first
    argument.
    """

    def __init__(self, func: Callable) -> None:
        self.dispatcher: dict[Enum, Callable] = {}
        self.func = func

    def _is_literal_type(self, type_: Any) -> bool:
        from typing import get_origin, Literal
        return get_origin(type_) is Literal

    def _is_valid_dispatch_type(self, enum: Enum | Callable) -> bool:
        if isinstance(enum, Enum):
            return True

        from typing import get_args
        return (
            self._is_literal_type(enum) and
            all(isinstance(arg, Enum) for arg in get_args(enum))
        )

    def register(
        self,
        enum: Enum | Callable,
        func: Callable | None = None
    ) -> Callable:
        if self._is_valid_dispatch_type(enum):
            if func is None:
                return lambda method: self.register(enum, method)
        else:
            if func is not None:
                raise TypeError(
                    'Invalid first argument to `register()`. '
                    f'{enum!r} is not an Enum or union type.'
                )
            ann = getattr(enum, '__annotations__', {})
            if not ann:
                raise TypeError(
                    f'Invalid first argument to `register()`: {enum!r}. '
                    'Use either `@register(EnumClass.value)`, '
                    'or plain `@register` on an annotated function.'
                )
            func = enum

            # only import typing if annotation parsing is necessary
            from typing import get_type_hints
            argname, enum = next(iter(get_type_hints(func).items()))
            if not self._is_valid_dispatch_type(enum):
                if self._is_literal_type(enum):
                    raise TypeError(
                        f'Invalid annotation for {argname!r}. '
                        f'{enum!r} not all arguments are Enums.'
                    )
                else:
                    raise TypeError(
                        f'Invalid annotation for {argname!r}. '
                        f'{enum!r} is not an Enum.'
                    )

        if self._is_literal_type(enum):
            from typing import get_args

            for arg in get_args(enum):
                self.dispatcher[arg] = func
        else:
            self.dispatcher[enum] = func

        return func

    def __get__(self, obj: object, cls: type[object] | None = None) -> Callable:
        def _method(*args, **kwargs) -> Any:
            method = self.dispatcher[args[0]]
            return method.__get__(obj, cls)(*args, **kwargs)

        update_wrapper(_method, self.func)
        return _method
