%pip -q install -U datasets huggingface_hub pyarrow tqdm numpy

import json
import os
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import (
    CommitOperationAdd,
    CommitOperationDelete,
    HfApi,
    hf_hub_download,
    login,
)
from tqdm.auto import tqdm

try:
    from google.colab import userdata
except Exception:
    userdata = None

print("Dependencies imported (anachronism keyword pass -- no tokenizer needed).")
