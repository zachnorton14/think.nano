# Source and destination dataset repositories.
SRC_REPO = "jbduran/think-dataset"
DST_REPO = "jbduran/think-dataset-clean"

# Hugging Face auth.
# Recommended in Colab: add a write token as a secret named HF_TOKEN.
HF_TOKEN = None
if userdata is not None:
    try:
        HF_TOKEN = userdata.get("HF_TOKEN")
    except Exception:
        HF_TOKEN = None

if not HF_TOKEN:
    HF_TOKEN = os.environ.get("HF_TOKEN")

if HF_TOKEN:
    login(token=HF_TOKEN, add_to_git_credential=False)
else:
    from huggingface_hub import notebook_login
    notebook_login()
    HF_TOKEN = True

api = HfApi(token=HF_TOKEN)

# Start-over controls. Leave these False for normal resumable runs.
CONFIRM_WIPE = False
FORCE_RECOMPUTE_PRIOR = False

# Structural filters.
MIN_CHARS_RAW = 500
MIN_CHARS_CLEAN = 500
MIN_PRINTABLE = 0.85
MAX_OCR_ARTIFACTS = 50

# Prior filter. p2.5-p97.5 removes about 5% by construction on the sampled docs.
PRIOR_BAND = (2.5, 97.5)
SAMPLE_SHARDS = 12
SAMPLE_DOCS = 20_000
TOKENIZE_CHARS = 50_000
RANDOM_SEED = 42

# Output settings. One input shard maps to one output shard with the same basename.
ROW_GROUP_SIZE = 64
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 3

# Local Colab working directories.
WORK_DIR = Path("/content/think_clean_work")
SRC_CACHE = WORK_DIR / "source"
OUT_DIR = WORK_DIR / "out"
PRIOR_DIR = WORK_DIR / "prior"
for d in [SRC_CACHE, OUT_DIR, PRIOR_DIR]:
    d.mkdir(parents=True, exist_ok=True)

random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

print(f"Source:      {SRC_REPO}")
print(f"Destination: {DST_REPO}")
print(f"Prior band:  p{PRIOR_BAND[0]}-p{PRIOR_BAND[1]}")
