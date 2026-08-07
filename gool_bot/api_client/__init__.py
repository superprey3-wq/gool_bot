"""
API Client модуль
"""

from api_client.infersports import InfersportsClient, get_infersports_client
from api_client.highlightly import HighlightlyClient, get_highlightly_client

__all__ = [
    'InfersportsClient',
    'get_infersports_client',
    'HighlightlyClient',
    'get_highlightly_client'
]
