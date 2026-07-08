"""Stage 1: build the 1930s banned list and upload it to the destination repo.

Seed = croqaz/vintage-ft-v1 banned.txt (D1, 1900 cutoff) embedded verbatim + a
supplement of post-1930 terms. ALLOW_1930 strips the pre-1931-legit entries for
the 1930 cutoff; EXTRA_1930_BANNED backfills clear post-1930 terms. The final list,
allow-list, removed-from-seed audit, and metadata are written under _banned/ in
{DST_REPO} and the total term count is printed.

Run:  python scripts/build_list.py
"""
import json
import re
import time

from huggingface_hub import CommitOperationAdd, hf_hub_download

import config
from common import api, HF_TOKEN, ensure_dst_repo


def _norm(term):
    """Normalize a term for matching: lowercase, collapse internal whitespace."""
    return re.sub(r"\s+", " ", term.strip().lower())


def _clean_terms(raw_iterable):
    """Drop blanks/comments/code-fence markers; normalize; dedupe (keep order)."""
    seen = set()
    out = []
    for line in raw_iterable:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("```"):
            continue
        t = _norm(s)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


# --- SEED: post-1900 anachronisms. This is croqaz/vintage-ft-v1 banned.txt
#     (the D1 "hard veto" list, built for a 1900 cutoff) embedded VERBATIM, plus
#     a supplementary section of post-1930 terms croqaz lacks. It intentionally
#     still contains pre-1931-legit terms (aeroplane, radio, einstein, quantum,
#     x-ray, ...); ALLOW_1930 removes them below, and _banned/removed_from_seed.json
#     records exactly what was stripped as the audit of the 1900 -> 1930 shift.
#     Embedded (not fetched) so the notebook is reproducible and offline-safe.


SEED_RAW = """
# Curated post-1900 anachronisms -> HARD VETO (D1).
# A hit forces the text to be dropped. Terms here are AUTHORITATIVE: they are
# never overridden by the allow-list (unlike the auto-parsed banned_seed.txt).
# Phrases match whole-word, case-insensitive; a short phrase ("world war") also
# matches longer mentions ("world war ii").

1000W of power
100W of power
180W of power
2000W of power
20th century fox
21st century
9/11
abortion law
Ada program
aeroplane
ai language model
aircraft
airliner
airplane
airport
always-on display
android phone
antibiotic
antimatter
apartheid
app store
arcade games
artificial intelligence
as an AI
astronaut
atomic bomb
automation
bash script
berlin wall
big bang
big-bang
binary pulsar
bioacoustic
black hole
blitzkrieg
blockchain
blog
blog post
blogger
bluetooth
boeing 777
bubble gum
bubblegum
C program
C#
c++
C++
cell phone
cell tower
cellphone
cellular connectivity
chatbot
chatgpt
chemotherapy
chromosome
cinema
climate change
Clojure function
Clojure program
code snippet
cold war
command-line
compiler
computer
COVID-19
CPU
credit card
credit-card
CSS
CSV file
d-day
dark energy
dark matter
database
DDR3
DDR4
DDR5
DDR6
DDR7
deep learning
desktop computer
digital edition
digital media
diode
DNA
download
drone
DVD
DynamoDB
e-book
e-commerce
e-learning
e-mail
ebook
effective field theory
electric beard trimmer
electric toothbrush
electro-optic
Elixir function
Elixir program
email
emoji
empire state building
EU countries
European Union
eurovision
Excel spreadsheet
Excel table
fascism
fascist
fax
ferromagnetic material
ferromagnetism
fiber-optic
fibre-optic
final fantasy X
first world war
FizzBuzz
fortran
Frenkel defect
FTP server
function in C
function in Go
function in R
gaming
gaming industry
gender affirming
gender nonconforming
gene expression
gene therapy
general relativity
genome
gestapo
gigabyte
Go code
Go function
Go program
godzilla
Golang function
Golang microservice
Golang program
GPS
GPU
graphene
gravitational redshift
great depression
Grignard reagent
hardware
harry potter
hashtag
haskell code
haskell function
haskell program
Hawking radiation
HDD
headphone
helicopter
Higgs boson
Higgs field
hip hop
hip-hop
hiroshima
hollywood
holocaust
hormone
HTML
http
HTTP POST
Hubble's Law
hydrogen bomb
illegal immigratio
internet
ionic compounds
iOS application
iPad
iPhone
iron curtain
iWatch
java applet
java class
java code
java function
java program
JavaScript
jazz
jet engine
jet flight
jetliner
korean war
kotlin function
kotlin program
laptop
Large Hadron Collider
large language model
laser
Lattice QCD
LCD
league of nations
lepton-jet
leptoquark
lesbian
lgbt
Liquid-crystal display
low bass
machine learning
matlab
mechanisation
mechanization
megabyte
metal-organic
metamaterial
Michelson-Morley experiment
microchip
microprocessor
microservice
microwave
minecraft
mobile phone
molecule
moon landing
motherboard
motion picture
movie
MQTT broker
mRNA
MySQL
NAFTA
navigation system
Navy Seals
nazi
nazism
neural network
neurology
neutron
Node.js
nuclear bomb
nuclear reaction
nuclear reactor
nuclear weapon
nuremberg trials
nylon
OCaml function
official website
omega-3
online
optical fiber
PDF version
pearl harbor
penicillin
perl function
perl program
perl script
PHP
pink floyd
pixel
plastic-free
plutonium
podcast
polyester
polyethylene
polymer
polystyrene
pornographic
PostgreSQL
PowerShell
program in C++
program in Javascript
program in Python
programming language
proton
python code
Python Flask
python function
python program
python script
pytorch
quantum
quantum chromodynamics
quantum field theory
quark-gluon plasma
R code
radar
radio broadcast
reality television
reality TV
reboot
Redis key-value
regular expression
REST API
RESTful API
rna
rock 'n' roll
rock and roll
rocket ship
Ruby code
Ruby function
Ruby program
Ruby script
Rust function
Rust program
same-sex marriage
satellite
satellite-dish
Scala code
Scala program
Schottky defect
screenplay
SDK
search engine
search-engine
second world war
selfie
semiconductor
server in Java
shamebloody
Shell command
smart phone
smart watch
smartphone
smartwatch
social media
software
sonar
soviet union
space race
space shuttle
space station
spacecraft
spaceflight
spaceship
special effects
spectral classification
spectrometry
spin electronics
spintronics
SQL
SSD
star wars
stellar classification
stereo
Super Bowl
super mario
superconductivity
superconductor
swift app
swift function
synthetic tissue
television
terrabyte
the beatles
the movies
trans activist
trans people
transistor
tRNA
trotsky
try-catch block
TV show
twentieth century
ultra lightweight
TypeScript
united nations
upload
ussr
vegan
veganism
video camera
video game
videogame
vietnam war
virtual reality
vitamin
web site
website
WebSocket
went viral
wi-fi
wifi
Wittig reagent
world war
WW1
WW2
WW3
wwi
wwii
www
X-files
X-men
X-ray astronomy
xanthan gum

# --- people ---
adolf hitler
albert einstein
anne sexton
benito mussolini
bob dylan
bob marley
carlos santana
donald trump
einstein
elvis presley
ernest hemingway
franklin roosevelt
franz kafka
gandhi
hitler
j. d. salinger
j. r. r. tolkien
j.d. salinger
j.r.r. tolkien
James Bond
john f. kennedy
john fitzgerald kennedy
joseph stalin
lenin
mahatma gandhi
mao zedong
marilyn monroe
martin luther king jr.
mussolini
Nikola Tesla
Robert Downey Jr.
stalin
sylvia plath
taylor swift
Tony Stark
vladimir lenin
walt disney
william faulkner

# --- brands (founded post-1900) ---
AstraZeneca
burger king
facebook
github
google
instagram
mcdonald's
mcdonalds
microsoft
netflix
nintendo
openai
panasonic
samsung
tiktok
twitter
youtube
# --- supplementary post-1930 terms (not in croqaz; added for 1930 coverage) ---
positron
deuterium
cyclotron
electron microscope
nuclear fission
nuclear fusion
manhattan project
chain reaction
radioactive fallout
carbon dating
radiocarbon
standard model
quantum entanglement
quantum computer
double helix
genetic engineering
stem cell
crispr
supersonic
cosmonaut
integrated circuit
semiconductor chip
silicon chip
personal computer
operating system
source code
web browser
web page
world wide web
usb
hyperlink
mobile app
transistor radio
world war ii
world war 2
nazi germany
nagasaki
new deal
isbn
paperback edition
project gutenberg
xerox
atom bomb
maser
jet aircraft
jet plane
nasa
nato
fbi
cia
wikipedia
bitcoin
cryptocurrency
coca-cola company
disney world
kleenex
"""

# --- ALLOW_1930: terms LEGITIMATE at a 1930 cutoff -> removed from the seed.
#     Each is attested in common use by 1930 or earlier. Whole-word, case-insensitive
#     matching means the base term also spares its longer mentions. Conservative:
#     when a term straddles ~1900-1935, ALLOW it (the log-prior filter is the backstop).
#     Deliberately NOT allowed (stay banned): neutron(1932), positron(1932),
#     deuterium(1931), empire state building(1931), franklin roosevelt(1933+ assoc).
ALLOW_1930 = {
    # aviation & transport (Wright 1903; airlines/airports common by the 1920s)
    "aeroplane", "airplane", "aircraft", "airliner", "airport", "aviation",
    "aviator", "airship", "zeppelin", "dirigible", "biplane", "monoplane",
    "automobile", "motorcar", "motor car", "motorcycle", "locomotive",
    "steamship", "submarine", "helicopter",
    # comms & media (all household terms by 1930)
    "radio", "radio broadcast", "wireless", "telephone", "telegraph", "telegram",
    "phonograph", "gramophone", "cinema", "cinematograph", "motion picture",
    "moving picture", "movie", "movies", "the movies", "film", "photograph",
    "photography", "camera", "video camera", "typewriter", "stereo", "microphone",
    "television",  # word coined 1900s; per conservative policy, allow
    # physics / chemistry attested <=1930 (Einstein 1905/15; QM 1925-27)
    "quantum", "quantum theory", "quantum mechanics", "quantum physics",
    "relativity", "theory of relativity", "special relativity", "general relativity",
    "photon", "electron", "proton", "atom", "atomic", "atomic theory", "isotope",
    "ion", "radioactivity", "radioactive", "radium", "uranium", "x-ray", "x ray",
    "xray", "roentgen", "spectroscopy", "spectrometry", "spectral classification",
    "stellar classification", "thermodynamics", "entropy", "electromagnetic",
    "ferromagnetism", "ferromagnetic material", "molecule", "ionic compounds",
    "michelson-morley experiment", "cathode ray", "vacuum tube", "polymer",
    "planck", "bohr", "rutherford", "curie",
    # biology / medicine <=1930
    "vitamin", "hormone", "insulin", "gene", "genetics", "chromosome", "heredity",
    "evolution", "natural selection", "darwin", "mendel", "bacteria", "bacterium",
    "virus", "vaccine", "vaccination", "antiseptic", "anesthesia", "anaesthesia",
    "neurology", "germ theory",
    # psychology / social <=1930
    "psychoanalysis", "freud", "subconscious", "unconscious", "psychology",
    # general modern-sounding but <=1930
    "electricity", "electric", "dynamo", "generator", "turbine", "engine",
    "petroleum", "gasoline", "petrol", "kerosene", "celluloid", "rubber",
    "skyscraper", "elevator", "escalator", "subway", "tram", "streetcar",
    "jazz", "ragtime", "aspirin", "plastic", "bakelite", "rayon",
    "mechanization", "mechanisation", "fascism", "fascist",
    # WWI-era history (WWI itself is pre-cutoff; WWII terms are added separately)
    "first world war", "world war", "the world war", "wwi", "ww1", "great war",
    "twentieth century", "nineteenth century", "league of nations",
    # people alive/active & famous by 1930
    "einstein", "albert einstein", "nikola tesla", "lenin", "vladimir lenin",
    "gandhi", "mahatma gandhi", "franz kafka", "leon trotsky", "trotsky",
    "joseph stalin", "stalin", "ernest hemingway", "william faulkner", "walt disney",
}
ALLOW_1930 = {_norm(t) for t in ALLOW_1930}

# --- EXTRA_1930_BANNED: unambiguously post-1930 terms to guarantee coverage
#     even if the seed missed them. Conservative: borderline items (penicillin,
#     antibiotic ~1940s clinical use) are included since they are clearly
#     post-1930 as common terms; if they over-fire, move them to ALLOW_1930. ---
EXTRA_1930_BANNED = {
    # physics/science firmly after 1930
    "neutron",              # Chadwick, 1932
    "positron",             # 1932
    "deuterium",            # 1931
    "nuclear fission",      # 1938
    "nuclear fusion",
    "nuclear reactor", "nuclear physics", "nuclear energy", "nuclear power",
    "atomic bomb", "atom bomb", "hydrogen bomb", "nuclear weapon",
    "manhattan project", "chain reaction",
    "antibiotic", "penicillin", "sulfa drug", "sulfanilamide",
    "dna", "rna", "double helix", "genome", "genetic code",
    "radar", "sonar", "jet engine", "jet aircraft", "jet plane",
    "television broadcast", "transistor",
    "cyclotron",            # 1932 (Lawrence)
    "electron microscope",  # 1931-33
    # computing / digital (all post-1930)
    "computer program", "digital computer", "electronic computer",
    "microprocessor", "microchip", "integrated circuit", "semiconductor",
    "internet", "world wide web", "website", "email", "e-mail", "software",
    "smartphone", "laser", "maser",
    # geopolitics / history post-1930
    "world war ii", "world war 2", "second world war", "cold war",
    "united nations", "nato", "nazi", "nazi germany", "holocaust", "auschwitz",
    "pearl harbor", "hiroshima", "nagasaki", "d-day", "normandy landing",
    "iron curtain", "berlin wall", "soviet union", "ussr",
    "spanish civil war",    # 1936
    # named orgs/entities post-1930
    "nasa", "fbi", "cia", "gestapo", "luftwaffe", "wehrmacht",
    # publishing / format
    "isbn", "paperback", "photocopy", "xerox", "ballpoint",
}
EXTRA_1930_BANNED = {_norm(t) for t in EXTRA_1930_BANNED}


FORMAT_TELL_PATTERNS = {
    "copyright_post_1930": r"(?:©|copyright|\(c\))\s*(?:19[3-9]\d|20\d\d)",
    "modern_year_reserved": r"all\s+rights\s+reserved",
    "isbn": r"\bisbn(?:-1[03])?\b",
    "url_www": r"\bwww\.",
    "url_http": r"https?://",
    "url_dotcom": r"\b[\w-]+\.(?:com|org|net|edu|gov|io)\b",
    "loc_cip": r"library\s+of\s+congress\s+cata-?\s*loging|cataloging-in-publication",
    "printed_usa_modern": r"printed\s+in\s+the\s+united\s+states\s+of\s+america",
    "gutenberg_license": r"project\s+gutenberg(?:-tm)?(?:\s+(?:license|ebook|literary))",
    "email_addr": r"\b[\w.-]+@[\w.-]+\.\w{2,}\b",
}

# ---------------------------------------------------------------------------
# TIER SYSTEM -- drop only on strong evidence, to kill polysemy false positives.
#
#   tier 1 (hard)  : one hit drops the doc. Coined well after 1930, no earlier
#                    sense; proper nouns of post-1930 people/brands/products.
#   tier 2 (mod)   : default for real anachronisms. Contributes to a drop but is
#                    not decisive alone (see decide_drop in filter_lib).
#   tier 3 (weak)  : polysemous / has a legitimate pre-1930 meaning ("compiler of
#                    this volume", bee "drone", birdsong "twitter", Black Hole of
#                    Calcutta). NEVER fires alone -- only corroborates.
#   strip  (bpl)   : reproduction / boilerplate artifact (URLs, "all rights
#                    reserved", "photocopy", edition notices). Never drops a doc;
#                    logged so the wrapper can be audited/stripped later.
#
# Assignment = category defaults are TIER 2; the explicit sets below override.
# ---------------------------------------------------------------------------

# Words with a real pre-1930 sense -> must never drop a document on their own.
TIER3_TERMS = {
    # --- from observed false positives ---
    "compiler", "hardware", "gaming", "gaming industry", "drone",
    "satellite", "satellite-dish", "twitter", "black hole", "deep learning",
    "holocaust", "pearl harbor", "great depression", "lesbian",
    # --- other clear polysemy / pre-1930 senses ---
    "computer", "automation", "online", "download", "upload", "reboot", "pixel",
    "diode", "microwave", "fax", "stereo", "antimatter", "supersonic",
    "chemotherapy", "omega-3", "low bass", "ultra lightweight",
    "special effects", "screenplay", "navigation system", "hollywood",
    "hip hop", "hip-hop", "rock and roll", "rock 'n' roll", "climate change",
    # 1931-32 physics: genuinely post-1930 but legitimately discussable in a
    # period text -> require corroboration rather than dropping alone.
    "positron", "neutron", "deuterium", "cyclotron", "antimatter",
    "plastic-free",
}

# Reproduction / boilerplate word-terms -> strip-only (never contribute to drop).
# (The FORMAT_TELL_PATTERNS regexes are treated as strip-only in code as well.)
STRIP_ONLY_TERMS = {
    "photocopy", "paperback", "paperback edition", "pdf version",
    "digital edition", "digital media", "e-book", "ebook",
    "official website", "web site", "website", "web page", "web browser",
    "project gutenberg", "www", "http", "online",
}

# Hard, unambiguous post-1930 coinages + proper nouns -> one hit drops.
TIER1_TERMS = {
    # modern brands / products / platforms
    "chatgpt", "openai", "github", "google", "facebook", "instagram", "tiktok",
    "youtube", "netflix", "microsoft", "samsung", "panasonic", "nintendo",
    "astrazeneca", "burger king", "mcdonald's", "mcdonalds", "disney world",
    "kleenex", "boeing 777", "coca-cola company", "iphone", "ipad", "iwatch",
    "android phone", "app store", "smartphone", "smart phone", "smartwatch",
    "smart watch", "blockchain", "bitcoin", "cryptocurrency", "covid-19",
    "pytorch", "node.js", "minecraft", "super mario", "final fantasy x",
    "godzilla", "star wars", "x-men", "x-files", "harry potter", "super bowl",
    "eurovision",
    # post-1930 named people
    "adolf hitler", "benito mussolini", "mussolini", "mao zedong",
    "donald trump", "taylor swift", "elvis presley", "bob dylan", "bob marley",
    "the beatles", "pink floyd", "marilyn monroe", "john f. kennedy",
    "john fitzgerald kennedy", "martin luther king", "robert downey jr.",
    "tony stark", "james bond", "carlos santana", "anne sexton", "sylvia plath",
    "j.r.r. tolkien", "j. r. r. tolkien", "j.d. salinger", "j. d. salinger",
    # unambiguous post-1930 tech / computing / science
    "transistor", "microprocessor", "microchip", "integrated circuit",
    "semiconductor chip", "silicon chip", "internet", "world wide web",
    "css", "html", "javascript", "typescript", "php", "fortran",
    "dna", "rna", "mrna", "trna", "crispr", "genome", "double helix",
    "stem cell", "gene therapy", "genetic engineering", "nylon",
    "wifi", "wi-fi", "bluetooth", "usb", "gpu", "cpu", "ssd", "hdd", "dvd",
    "laptop", "quantum computer", "quantum chromodynamics",
    "quantum field theory", "large hadron collider", "higgs boson",
    "higgs field", "hawking radiation", "dark matter", "dark energy",
    "graphene", "spintronics", "metamaterial",
    "space shuttle", "space station", "moon landing", "spaceflight",
    "spacecraft", "cosmonaut", "astronaut", "nuclear weapon", "nuclear reactor",
    "hydrogen bomb", "atomic bomb", "atom bomb", "manhattan project",
    "nuremberg trials", "auschwitz", "berlin wall", "iron curtain", "cold war",
    "world war ii", "world war 2", "second world war", "wwii", "ww2", "d-day",
}


def assign_tiers(final_terms):
    """Map every banned term to a tier: 1, 2, 3, or 'strip'.

    Precedence: strip-only > tier 3 > tier 1 > default tier 2. (Strip and tier-3
    win over tier-1 so an ambiguous/boilerplate term is never treated as hard.)
    Returns (tiers_by_term, counts).
    """
    strip = {_norm(t) for t in STRIP_ONLY_TERMS}
    t3 = {_norm(t) for t in TIER3_TERMS} - strip
    t1 = {_norm(t) for t in TIER1_TERMS} - strip - t3

    tiers = {}
    for t in final_terms:
        if t in strip:
            tiers[t] = "strip"
        elif t in t3:
            tiers[t] = 3
        elif t in t1:
            tiers[t] = 1
        else:
            tiers[t] = 2
    counts = {
        "tier1": sum(1 for v in tiers.values() if v == 1),
        "tier2": sum(1 for v in tiers.values() if v == 2),
        "tier3": sum(1 for v in tiers.values() if v == 3),
        "strip": sum(1 for v in tiers.values() if v == "strip"),
    }
    return tiers, counts


def build_banned_list():
    """Construct the final banned term list from seed + allow + extra. Returns
    (final_terms_sorted, meta_dict, removed_from_seed_list)."""
    seed = _clean_terms(SEED_RAW.splitlines())
    seed_set = set(seed)

    removed_from_seed = sorted(seed_set & ALLOW_1930)
    kept_from_seed = seed_set - ALLOW_1930

    # Guard: never let an allow-listed term sneak back in via EXTRA.
    extra_effective = EXTRA_1930_BANNED - ALLOW_1930
    added_by_extra = sorted(extra_effective - kept_from_seed)

    final = sorted(kept_from_seed | extra_effective)
    tiers, tier_counts = assign_tiers(final)

    meta = {
        "cutoff_year": config.CUTOFF_YEAR,
        "n_seed": len(seed),
        "n_removed_by_allow": len(removed_from_seed),
        "n_added_by_extra": len(added_by_extra),
        "n_allow_list": len(ALLOW_1930),
        "n_format_tells": len(FORMAT_TELL_PATTERNS),
        "n_final_terms": len(final),
        "n_total_banned_signals": len(final) + len(FORMAT_TELL_PATTERNS),
        "tier_counts": tier_counts,
        "drop_rule": "1x tier1  OR  (>=2 distinct tier2/tier3 with >=1 tier2). "
                     "tier3 never fires alone; strip-only never contributes.",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy": "tiered_confidence",
    }
    return final, meta, removed_from_seed, added_by_extra, tiers


# Terms that contain punctuation the word-tokenizer would split (9/11, c++, ...).


def try_download_banned_list():
    """Load a cached banned list + tiers from the destination repo if present.

    Requires tiers.json to be present; a pre-tier cached list is treated as a
    cache miss so it gets rebuilt with tiers.
    """
    try:
        list_path = hf_hub_download(config.DST_REPO, "_banned/banned_list.txt", repo_type="dataset", token=HF_TOKEN)
        meta_path = hf_hub_download(config.DST_REPO, "_banned/list_meta.json", repo_type="dataset", token=HF_TOKEN)
        tier_path = hf_hub_download(config.DST_REPO, "_banned/tiers.json", repo_type="dataset", token=HF_TOKEN)
        with open(list_path, "r", encoding="utf-8") as f:
            terms = [_norm(l) for l in f if l.strip()]
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        with open(tier_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        # tiers.json stores ints as JSON strings for "strip"; normalize back.
        tiers = {k: (v if v == "strip" else int(v)) for k, v in raw.items()}
        print("Loaded cached banned list + tiers from destination repo.")
        return terms, meta, tiers
    except Exception:
        return None, None, None


def _write_tier_files(d, tiers):
    """Write per-tier text files + tiers.json to local dir d; return their paths."""
    buckets = {1: [], 2: [], 3: [], "strip": []}
    for term, tier in tiers.items():
        buckets[tier].append(term)
    paths = {}
    for tier, name in [(1, "tier1.txt"), (2, "tier2.txt"), (3, "tier3.txt"), ("strip", "strip_only.txt")]:
        p = d / name
        p.write_text("\n".join(sorted(buckets[tier])) + "\n", encoding="utf-8")
        paths[name] = p
    tj = d / "tiers.json"
    with open(tj, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in sorted(tiers.items())}, f, indent=2)
    paths["tiers.json"] = tj
    return paths


def build_and_upload_banned_list():
    final, meta, removed_from_seed, added_by_extra, tiers = build_banned_list()
    config.ensure_dirs()
    d = config.BANNED_DIR
    (d / "banned_list.txt").write_text("\n".join(final) + "\n", encoding="utf-8")
    (d / "allow_list.txt").write_text("\n".join(sorted(ALLOW_1930)) + "\n", encoding="utf-8")
    with open(d / "removed_from_seed.json", "w", encoding="utf-8") as f:
        json.dump({"removed_from_seed_because_pre_1931": removed_from_seed,
                   "added_by_extra_1930_banned": added_by_extra}, f, indent=2, sort_keys=True)
    with open(d / "list_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
    with open(d / "format_tells.json", "w", encoding="utf-8") as f:
        json.dump(FORMAT_TELL_PATTERNS, f, indent=2, sort_keys=True)
    tier_paths = _write_tier_files(d, tiers)

    ops = [
        CommitOperationAdd("_banned/banned_list.txt", str(d / "banned_list.txt")),
        CommitOperationAdd("_banned/allow_list.txt", str(d / "allow_list.txt")),
        CommitOperationAdd("_banned/removed_from_seed.json", str(d / "removed_from_seed.json")),
        CommitOperationAdd("_banned/list_meta.json", str(d / "list_meta.json")),
        CommitOperationAdd("_banned/format_tells.json", str(d / "format_tells.json")),
    ]
    ops += [CommitOperationAdd(f"_banned/{name}", str(p)) for name, p in tier_paths.items()]

    api.create_commit(
        repo_id=config.DST_REPO, repo_type="dataset", operations=ops,
        commit_message=(f"add 1930s tiered banned list ({meta['n_final_terms']} terms; "
                        f"tiers {meta['tier_counts']})"),
    )
    return final, meta, tiers


def load_or_build():
    """Return (banned_terms, meta, tiers): cached copy unless FORCE_REBUILD_LIST."""
    ensure_dst_repo()
    if config.FORCE_REBUILD_LIST:
        terms, meta, tiers = None, None, None
    else:
        terms, meta, tiers = try_download_banned_list()
    if terms is None:
        terms, meta, tiers = build_and_upload_banned_list()
    return terms, meta, tiers


def main():
    terms, meta, tiers = load_or_build()
    print("=" * 60)
    print("BANNED LIST SUMMARY (tiered)")
    print("=" * 60)
    print(json.dumps(meta, indent=2, sort_keys=True))
    tc = meta.get("tier_counts", {})
    print(f"\nTOTAL WORDS/PHRASES IN BANNED LIST: {len(terms):,}")
    print(f"  tier 1 (hard, 1 hit drops):        {tc.get('tier1', 0):,}")
    print(f"  tier 2 (moderate):                 {tc.get('tier2', 0):,}")
    print(f"  tier 3 (weak, never fires alone):  {tc.get('tier3', 0):,}")
    print(f"  strip-only (boilerplate, no drop): {tc.get('strip', 0):,}")
    print(f"Plus {len(FORMAT_TELL_PATTERNS)} format-tell patterns (strip-only).")
    return terms, meta, tiers


if __name__ == "__main__":
    main()
