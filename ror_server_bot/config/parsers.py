from pathlib import Path

import yaml
from defusedxml import ElementTree

from .models import (
    Announcements,
    Config,
    RoRClientConfig,
    ServerConfig,
    UserConfig,
)


def parse_yaml(file_path: Path) -> Config:
    """Parse a yaml file into a Config object.

    :param file_path: The path to the yaml file.
    :return: The Config object.
    """
    return Config.model_validate(yaml.safe_load(file_path.read_text()))


def parse_json(file_path: Path) -> Config:
    """Parse a json file into a Config object.

    :param file_path: The path to the json file.
    :return: The Config object.
    """
    return Config.model_validate_json(file_path.read_text())

def parse_xml(file_path: Path) -> Config:
    """Parse an xml file into a Config object.

    :param file_path: The path to the xml file.
    :return: The Config object.
    """
    tree = ElementTree.parse(file_path)
    root = tree.getroot()

    return Config(
        truck_blacklist=Path(root.find('truck_blacklist').text),
        ror_clients=[
            RoRClientConfig(
                id=client.find('id').text,
                enabled=client.find('enabled').text,
                server=ServerConfig(
                    host=client.find('server/host').text,
                    port=client.find('server/port').text,
                    password=client.find('server/password').text,
                ),
                user=UserConfig(
                    name=client.find('user/name').text,
                    token=client.find('user/token').text,
                    language=client.find('user/language').text,
                ),
                discord_channel_id=client.find('discord_channel_id').text,
                announcements=Announcements(
                    messages=[
                        message.text for message in
                        client.find('announcements/messages')
                    ],
                    delay=client.find('announcements/delay').text,
                    color=client.find('announcements/color').text,
                    enabled=client.find('announcements/enabled').text,
                ),
                reconnection_interval=client.find('reconnection_interval').text,
                reconnection_tries=client.find('reconnection_tries').text,
            )
            for client in root.find('ror_clients')
        ],
    )

def parse_file(file_path: Path) -> Config:
    """Parse a file into a Config object.

    :param file_path: The path to the config file.
    :return: The Config object.
    """
    match file_path.suffix:
        case '.json':
            return parse_json(file_path)
        case '.yaml':
            return parse_yaml(file_path)
        case '.xml':
            return parse_xml(file_path)
        case _:
            raise ValueError('Unsupported config file type')
