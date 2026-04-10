import os
import logging
from datetime import datetime
from config.settings import settings

os.makedirs(settings.LOG_DIR, exist_ok=True)

log_filename = os.path.join(
    settings.LOG_DIR, f"replacer_{datetime.now().strftime('%Y%m%d')}.log"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("product_replacer")
