import logging

import aiohttp

REQUEST_TIMEOUT = 30
_LOGGER = logging.getLogger(__name__)


async def get(url):
    """Http GET helper."""
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.get(
                url, headers={"Accept": "application/json"}
            ) as response:
                if response.status == 200:
                    return await response.text()
                _LOGGER.error("GET %s: %s", url, response.status)
                return
        except aiohttp.ClientConnectorError as err:
            _LOGGER.error("Connection error: %s", err)
