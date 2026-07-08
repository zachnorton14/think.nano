# Source and destination dataset repositories.
# Source is the already-cleaned corpus from the first notebook; destination is new.
SRC_REPO = "jbduran/think-dataset-clean"
DST_REPO = "jbduran/think-dataset-clean-1930s"

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

# The destination repo does not exist yet on the first run. Create it here.
# exist_ok=True makes this a no-op on every subsequent (resumed) run.
api.create_repo(repo_id=DST_REPO, repo_type="dataset", exist_ok=True, private=False)
print(f"Ensured destination dataset repo exists: {DST_REPO}")

# Cutoff. Anything AFTER 1930 is an anachronism for this corpus (1930 and earlier is fine).
CUTOFF_YEAR = 1930

# How many DISTINCT banned terms must appear before a document is dropped.
# 1 == Hla's method: a single hit anywhere scraps the whole document.
MIN_BANNED_HITS = 1

# Start-over / rebuild controls. Leave False for normal resumable runs.
CONFIRM_WIPE = False        # Stage 0: delete generated shards/stats/hits from DST_REPO.
WIPE_BANNED_LIST = False     # also delete the _banned/ list artifacts when wiping.
FORCE_REBUILD_LIST = False   # rebuild the banned list even if one is cached on HF.

# Output settings. One input shard maps to one output shard with the same basename.
# Kept identical to the source notebook so shards stay ~the same size.
ROW_GROUP_SIZE = 64
COMPRESSION = "zstd"
COMPRESSION_LEVEL = 3

# Scan window per document. Anachronistic content (modern forewords, footnotes,
# copyright/ISBN pages, digitization boilerplate) sits at the FRONT of a book, and
# occasionally the back -- essentially never buried mid-chapter. Scanning a capped
# head + tail keeps per-document cost bounded and predictable even for huge OCR
# books, while still catching the leaks the filter exists for.
# Set SCAN_CHARS = None to scan the entire document (slower on multi-MB books).
SCAN_CHARS = 300_000       # ~first 300k chars (roughly the first ~50-60k words)
SCAN_TAIL_CHARS = 50_000   # also scan the last ~50k chars; set 0 to disable

# Local Colab working directories.
WORK_DIR = Path("/content/think_1930s_work")
SRC_CACHE = WORK_DIR / "source"
OUT_DIR = WORK_DIR / "out"
BANNED_DIR = WORK_DIR / "banned"
for d in [SRC_CACHE, OUT_DIR, BANNED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

RANDOM_SEED = 42
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

print(f"Source:       {SRC_REPO}")
print(f"Destination:  {DST_REPO}")
print(f"Cutoff year:  {CUTOFF_YEAR} (drop docs mentioning anything after this)")
print(f"Drop rule:    >= {MIN_BANNED_HITS} distinct banned term(s) per document")
