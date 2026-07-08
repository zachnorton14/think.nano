# === Install dependencies ===================================================
%pip -q install -U datasets huggingface_hub pyarrow tqdm numpy

import os
from pathlib import Path

from huggingface_hub import HfApi, login

try:
    from google.colab import userdata
except Exception:
    userdata = None

# === Authenticate to Hugging Face ==========================================
# Preferred: add a WRITE token as a Colab secret named HF_TOKEN.
HF_TOKEN = None
if userdata is not None:
    try:
        HF_TOKEN = userdata.get("HF_TOKEN")
    except Exception:
        HF_TOKEN = None
HF_TOKEN = HF_TOKEN or os.environ.get("HF_TOKEN")
if not HF_TOKEN:
    from huggingface_hub import notebook_login
    notebook_login()
    HF_TOKEN = HfApi().token

# Export so the stage scripts (separate processes) can authenticate.
os.environ["HF_TOKEN"] = HF_TOKEN
login(token=HF_TOKEN, add_to_git_credential=True)

# === Configuration (exported as env vars for the scripts) ==================
DST_REPO = "jbduran/think-dataset-clean-1930s"
SRC_REPO = "jbduran/think-dataset-clean"
os.environ["SRC_REPO"] = SRC_REPO
os.environ["DST_REPO"] = DST_REPO
os.environ["WORK_DIR"] = "/content/think_1930s_work"

# Scan window + policy (see scripts/config.py for meaning). Tweak here if needed.
os.environ["CUTOFF_YEAR"] = "1930"
os.environ["MIN_BANNED_HITS"] = "1"
os.environ["SCAN_CHARS"] = "300000"
os.environ["SCAN_TAIL_CHARS"] = "50000"

api = HfApi(token=HF_TOKEN)
api.create_repo(repo_id=DST_REPO, repo_type="dataset", exist_ok=True, private=False)
print(f"Authenticated. Destination repo ready: {DST_REPO}")
