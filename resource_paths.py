"""Resource locations for development and portable builds."""
import os
from pathlib import Path
ROOT = Path(os.environ.get('RONA_RESOURCE_DIR', Path(__file__).resolve().parent)).resolve()
