from pathlib import Path
from xml.etree.ElementTree import Element

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

    def find(element: Element, tag: str) -> Element:
        _element = element.find(tag)
        if _element is None:
            raise ValueError(f'Element {tag} not found')
        return _element

    return Config(
        truck_blacklist=find(root, 'truck_blacklist').text,
        ror_clients=[
            RoRClientConfig(
                id=find(client, 'id').text,
                enabled=find(client, 'enabled').text,
                server=ServerConfig(
                    host=find(client, 'server/host').text,
                    port=find(client, 'server/port').text,
                    password=find(client, 'server/password').text,
                ),
                user=UserConfig(
                    name=find(client, 'user/name').text,
                    token=find(client, 'user/token').text,
                    language=find(client, 'user/language').text,
                ),
                discord_channel_id=find(client, 'discord_channel_id').text,
                announcements=Announcements(
                    messages=[
                        message.text for message in
                        find(client, 'announcements/messages')
                    ],
                    delay=find(client, 'announcements/delay').text,
                    color=find(client, 'announcements/color').text,
                    enabled=find(client, 'announcements/enabled').text,
                ),
                reconnection_interval=find(
                    client, 'reconnection_interval').text,
                reconnection_tries=find(client, 'reconnection_tries').text,
            )
            for client in find(root, 'ror_clients')
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
