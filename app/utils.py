import logging
import random

from config import RadioConfig
from pyradios import RadioBrowser

logger = logging.getLogger(__name__)


def search_radio_station_by_tags(tags: str | list[str]) -> RadioConfig | None:
    logger.info(f"Searching for radio stations with tags: {tags}")
    rb = RadioBrowser()

    # Convert list to comma-separated string if needed
    tag_string = ",".join(tags) if isinstance(tags, list) else tags
    results = rb.search(tag_list=tag_string)

    if results and isinstance(results, list) and len(results) > 0:
        # Filter out stations with empty URLs
        valid_results = [r for r in results if r.get("url_resolved")]

        if not valid_results:
            logger.warning(f"No stations with valid URLs found for tags: {tags}")
            return None

        logger.info(f"Found {len(valid_results)} valid stations, selecting random one")
        result = random.choice(valid_results)
        logger.info(f"Selected station: {result['name']} - {result['url_resolved']}")

        return RadioConfig(
            name=result["name"],
            stream_url=result["url_resolved"],
        )

    logger.warning(f"No stations found for tags: {tags}")
    return None
