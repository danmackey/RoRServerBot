import math
from collections.abc import Callable, Generator, Iterator
from typing import Any

from pydantic import BaseModel


class Vector3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def __getitem__(self, index: int) -> float:
        return [self.x, self.y, self.z][index]

    def __setitem__(self, index: int, value: float) -> None:
        if index == 0:
            self.x = value
        elif index == 1:
            self.y = value
        elif index == 2:
            self.z = value
        else:
            raise IndexError(index)

    def __iter__(self) -> Iterator[float]:  # type: ignore[override]
        return iter((self.x, self.y, self.z))

    def __len__(self) -> int:
        return len(Vector3.model_fields)

    def __hash__(self) -> int:
        return hash((self.x, self.y, self.z))

    def __eq__(self, __value: object) -> bool:
        if isinstance(__value, Vector3):
            return (
                self.x == __value.x
                and self.y == __value.y
                and self.z == __value.z
            )
        elif (
            isinstance(__value, tuple)
            and len(__value) == len(Vector3.model_fields)
            and all(isinstance(v, int | float) for v in __value)
        ):
            return bool(
                self.x == __value[0]
                and self.y == __value[1]
                and self.z == __value[2]
            )
        return NotImplemented

    def __lt__(self, __value: object) -> bool:
        if isinstance(__value, Vector3):
            return (
                self.x < __value.x
                and self.y < __value.y
                and self.z < __value.z
            )
        elif (
            isinstance(__value, tuple)
            and len(__value) == len(Vector3.model_fields)
            and all(isinstance(v, int | float) for v in __value)
        ):
            return bool(
                self.x < __value[0]
                and self.y < __value[1]
                and self.z < __value[2]
            )
        return NotImplemented

    def __le__(self, __value: object) -> bool:
        return self.__lt__(__value) or self.__eq__(__value)

    def __gt__(self, __value: object) -> bool:
        if isinstance(__value, Vector3):
            return (
                self.x > __value.x
                and self.y > __value.y
                and self.z > __value.z
            )
        elif (
            isinstance(__value, tuple)
            and len(__value) == len(Vector3.model_fields)
            and all(isinstance(v, int | float) for v in __value)
        ):
            return bool(
                self.x > __value[0]
                and self.y > __value[1]
                and self.z > __value[2]
            )
        return NotImplemented

    def __ge__(self, __value: object) -> bool:
        return self.__gt__(__value) or self.__eq__(__value)

    def __repr__(self) -> str:
        return f'Vector3({self.x}, {self.y}, {self.z})'

    def __str__(self) -> str:
        return f'({self.x}, {self.y}, {self.z})'

    def __format__(self, format_spec: str) -> str:
        return (
            f'({self.x:{format_spec}}, '
            f'{self.y:{format_spec}}, '
            f'{self.z:{format_spec}})'
        )

    def __pretty__(  # type: ignore[override]
        self,
        fmt: Callable[[Any], Any],
        **kwargs: Any
    ) -> Generator[Any, None, None]:
        yield self.__repr_name__() + '('  # type: ignore[misc]
        for i, (name, value) in enumerate(self.model_dump().items()):
            if name is not None:
                yield name + '='
            yield fmt(value)
            if i < len(self) - 1:
                yield ', '
        yield ')'

    def distance(self, other: 'Vector3') -> float:
        """Calculates the distance to another Vector3

        :param other: A Vector3 to calculate the distance to
        :return: The distance to the other Vector3
        """
        return math.sqrt(
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )
