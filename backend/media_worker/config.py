"""Non-secret defaults and environment settings for the existing Media Worker."""

import os
from pathlib import Path

USERNAME = os.getenv('AUTOCLIPPER_SOURCE_USERNAME', 'mandala.auto.kediri')
CHANNEL_ID = os.getenv(
    'AUTOCLIPPER_SOURCE_CHANNEL_ID',
    'MS4wLjABAAAARRCOc1BxQyl9stiiH_Ow0X6508sdbl'
    'TUyU7zoTpuwDnuasR9zOUesydpwPbbBVOo',
)
ROOT = Path(os.getenv('AUTOCLIPPER_SOURCE_ROOT', '/data/source'))
MAX_BYTES = int(os.getenv('AUTOCLIPPER_MAX_SOURCE_BYTES', str(150 * 1024 * 1024)))
PORT = int(os.getenv('AUTOCLIPPER_WORKER_PORT', '3002'))
PGPORT = os.getenv('PGPORT', '5432')
PGDATABASE = os.getenv('PGDATABASE', 'mandala_autoclipper')
