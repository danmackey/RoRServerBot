import json
import logging
import re
from pathlib import Path
from typing import Self

from pydantic import BaseModel, TypeAdapter

from ror_server_bot.ror_bot.enums import ActorType

logger = logging.getLogger(__name__)

truckfile_re = re.compile(
    r'((?P<guid>[a-z0-9]*)\-)?((.*)UID\-)?(?P<name>.*)'
    r'\.(?P<type>truck|car|load|airplane|boat|trailer|train|fixed)'
)


class TruckFile(BaseModel):
    filename: Path
    """The full filename of the .truck file including the extension."""
    guid: str | None = None
    """The guid included in the filename (optional)."""
    name: str
    """The display name of the actor."""
    type: ActorType
    """The type of the actor."""

    @classmethod
    def from_filename(
        cls,
        json_file: Path,
        truck_filename: str
    ) -> Self:
        """Creates a truck file from the filename.

        :param json_file: The json file to get the truck file name from.
        :param filename: The filename to create the truck file from.
        :return: The truck file created from the filename.
        """
        validator = TypeAdapter(dict[str, str])
        with open(json_file) as file:
            truck_filenames = validator.validate_python(json.load(file))
        name = truck_filenames.get(truck_filename)
        match = truckfile_re.search(truck_filename)
        if name is None and match is not None:
            return cls(filename=truck_filename, **match.groupdict())
        elif name is not None:
            return cls(
                filename=truck_filename,
                name=name,
                type=truck_filename.rsplit('.', maxsplit=1)[-1].lower()
            )
        else:
            raise ValueError(
                f'Could not parse truck file name: {truck_filename}'
            )
