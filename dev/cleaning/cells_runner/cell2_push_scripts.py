# === Push the pipeline scripts to Hugging Face, then clone the repo =========
# The pipeline lives in a local `scripts/` folder. Bring it into this Colab
# session first (drag-and-drop the folder into the file browser, or mount Drive).
# This cell uploads it to `scripts/` in the destination repo, then clones the
# repo so every stage runs from a clean checkout on HF.

LOCAL_SCRIPTS = Path("scripts")   # adjust if you placed it elsewhere in Colab

assert LOCAL_SCRIPTS.is_dir(), (
    f"Could not find '{LOCAL_SCRIPTS}/' in this Colab session. Upload the scripts "
    "folder (config.py, common.py, build_list.py, filter_lib.py, run_filter.py, "
    "report.py, wipe.py) into the working directory and re-run this cell."
)

api.upload_folder(
    repo_id=DST_REPO,
    repo_type="dataset",
    folder_path=str(LOCAL_SCRIPTS),
    path_in_repo="scripts",
    commit_message="upload/update 1930s pipeline scripts",
)
print("Uploaded scripts/ to HF.")

# Clone the repo (or pull if already cloned) and run everything from there.
CLONE_DIR = Path("/content/think-dataset-clean-1930s")
if CLONE_DIR.exists():
    !cd "{CLONE_DIR}" && git pull --quiet
else:
    !git clone --quiet "https://huggingface.co/datasets/{DST_REPO}" "{CLONE_DIR}"

RUN_DIR = CLONE_DIR / "scripts"
print(f"Running stages from: {RUN_DIR}")
!ls -la "{RUN_DIR}"
