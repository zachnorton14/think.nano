%pip -q install -U datasets huggingface_hub pyarrow transformers tqdm numpy

import json
import math
import os
import random
import re
import shutil
import tempfile
import time
import unicodedata
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
from transformers import GPT2TokenizerFast

try:
    from google.colab import userdata
except Exception:
    userdata = None

print("Dependencies imported.")
