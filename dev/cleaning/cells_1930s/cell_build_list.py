# ---------------------------------------------------------------------------
# BANNED-LIST CONSTRUCTION
#
# Goal: a whole-word keyword list of terms that could ONLY appear in text
# written after 1930, used to drop documents that leaked modern content
# (editor forewords, modern footnotes, reprint boilerplate, etc.).
#
# Sources for the seed:
#   - croqaz/vintage-ft-v1 banned.txt (the D1 "hard veto" list) -- built for a
#     1900 cutoff.
#   - Michael Hla's gpt1900 post-1900 physics keywords.
# Because both target 1900, many of their entries (radio, aeroplane, Einstein,
# relativity, quantum, X-ray, ...) are LEGITIMATE by 1930 and are removed here
# via ALLOW_1930. We then add EXTRA_1930_BANNED for clearly post-1930 terms.
#
# Policy: CONSERVATIVE / high precision. When a term straddles ~1900-1935 we
# keep it ALLOWED rather than risk dropping legitimate 1930s texts. The upstream
# GPT-2 log-prior filter (previous notebook) is the statistical backstop.
# ---------------------------------------------------------------------------


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
#     Source: https://huggingface.co/datasets/croqaz/vintage-ft-v1/blob/main/banned.txt
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

# --- FORMAT-TELL regexes: extremely high precision; near-zero false positives.
#     These mark modern reprints / digitizations regardless of topical words. ---
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

    meta = {
        "cutoff_year": CUTOFF_YEAR,
        "n_seed": len(seed),
        "n_removed_by_allow": len(removed_from_seed),
        "n_added_by_extra": len(added_by_extra),
        "n_allow_list": len(ALLOW_1930),
        "n_format_tells": len(FORMAT_TELL_PATTERNS),
        "n_final_terms": len(final),
        "n_total_banned_signals": len(final) + len(FORMAT_TELL_PATTERNS),
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "policy": "conservative_high_precision",
    }
    return final, meta, removed_from_seed, added_by_extra


# Terms that contain punctuation the word-tokenizer would split (9/11, c++, ...).
# These are matched with explicit literal regexes instead of the token scanner.
PUNCT_TERM_PATTERNS = {
    "9/11": r"9/11",
    "c#": r"\bc#",
    "c++": r"\bc\+\+",
    "node.js": r"\bnode\.js\b",
}

# Word tokenizer for the fast scanner. The document is lowercased first, so this
# only needs the lowercase class. A token starts with a letter/digit and may
# contain internal apostrophes/hyphens (so "mcdonald's", "hip-hop" stay intact).
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def compile_matchers(banned_terms):
    """Build a fast matcher instead of one giant regex alternation.

    A 400+ term alternation in Python's `re` is O(terms) work at every position
    in the text, which is seconds per multi-MB book. Instead:
      - single-word terms  -> membership test against a frozenset (O(1) per token)
      - multi-word phrases -> gated by first word: only tested where their leading
                              token actually occurs (no alternation scan)
      - punctuation terms  -> a handful of explicit literal regexes
      - format tells       -> the existing high-precision regexes (already cheap)
    This is ~35x faster than the alternation with identical results.
    """
    single = set()
    phrases_by_first = {}   # first_word -> [(full_phrase, [word, ...]), ...]
    for t in banned_terms:
        tl = t.lower()
        if tl in PUNCT_TERM_PATTERNS:
            continue  # handled by the punct regexes below
        words = tl.split()
        if len(words) == 1 and TOKEN_RE.fullmatch(tl):
            single.add(tl)
        else:
            phrases_by_first.setdefault(words[0], []).append((tl, words))
    # Longest phrase first within each bucket so we record the most specific match.
    for k in phrases_by_first:
        phrases_by_first[k].sort(key=lambda x: -len(x[1]))

    format_res = {
        name: re.compile(pat, re.IGNORECASE)
        for name, pat in FORMAT_TELL_PATTERNS.items()
    }
    punct_res = {
        name: re.compile(pat, re.IGNORECASE)
        for name, pat in PUNCT_TERM_PATTERNS.items()
    }
    return {
        "single": frozenset(single),
        "phrases_by_first": phrases_by_first,
        "punct_res": punct_res,
        "format_res": format_res,
    }


def try_download_banned_list():
    """Load a cached banned list from the destination repo if present."""
    try:
        list_path = hf_hub_download(DST_REPO, "_banned/banned_list.txt", repo_type="dataset", token=HF_TOKEN)
        meta_path = hf_hub_download(DST_REPO, "_banned/list_meta.json", repo_type="dataset", token=HF_TOKEN)
        with open(list_path, "r", encoding="utf-8") as f:
            terms = [_norm(l) for l in f if l.strip()]
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        print("Loaded cached banned list from destination repo.")
        return terms, meta
    except Exception:
        return None, None


def build_and_upload_banned_list():
    final, meta, removed_from_seed, added_by_extra = build_banned_list()

    local_list = BANNED_DIR / "banned_list.txt"
    local_allow = BANNED_DIR / "allow_list.txt"
    local_removed = BANNED_DIR / "removed_from_seed.json"
    local_meta = BANNED_DIR / "list_meta.json"
    local_tells = BANNED_DIR / "format_tells.json"

    with open(local_list, "w", encoding="utf-8") as f:
        f.write("\n".join(final) + "\n")
    with open(local_allow, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(ALLOW_1930)) + "\n")
    with open(local_removed, "w", encoding="utf-8") as f:
        json.dump(
            {"removed_from_seed_because_pre_1931": removed_from_seed,
             "added_by_extra_1930_banned": added_by_extra},
            f, indent=2, sort_keys=True,
        )
    with open(local_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)
    with open(local_tells, "w", encoding="utf-8") as f:
        json.dump(FORMAT_TELL_PATTERNS, f, indent=2, sort_keys=True)

    api.create_commit(
        repo_id=DST_REPO,
        repo_type="dataset",
        operations=[
            CommitOperationAdd(path_in_repo="_banned/banned_list.txt", path_or_fileobj=str(local_list)),
            CommitOperationAdd(path_in_repo="_banned/allow_list.txt", path_or_fileobj=str(local_allow)),
            CommitOperationAdd(path_in_repo="_banned/removed_from_seed.json", path_or_fileobj=str(local_removed)),
            CommitOperationAdd(path_in_repo="_banned/list_meta.json", path_or_fileobj=str(local_meta)),
            CommitOperationAdd(path_in_repo="_banned/format_tells.json", path_or_fileobj=str(local_tells)),
        ],
        commit_message=f"add 1930s banned list ({meta['n_final_terms']} terms)",
    )
    return final, meta


# Build (or load cached) the banned list.
if not FORCE_REBUILD_LIST:
    BANNED_TERMS, BANNED_META = try_download_banned_list()
else:
    BANNED_TERMS, BANNED_META = None, None

if BANNED_TERMS is None:
    BANNED_TERMS, BANNED_META = build_and_upload_banned_list()

MATCHER = compile_matchers(BANNED_TERMS)
# Exposed for the filter/report cells:
FORMAT_RES = MATCHER["format_res"]          # high-precision format-tell regexes
PUNCT_RES = MATCHER["punct_res"]            # literal-punctuation term regexes
SINGLE_TERMS = MATCHER["single"]            # single-word banned terms (set)
PHRASES_BY_FIRST = MATCHER["phrases_by_first"]

_n_single = len(SINGLE_TERMS)
_n_phrase = sum(len(v) for v in PHRASES_BY_FIRST.values())
_n_punct = len(PUNCT_RES)

print("=" * 60)
print("BANNED LIST SUMMARY")
print("=" * 60)
print(json.dumps(BANNED_META, indent=2, sort_keys=True))
print(f"\nTOTAL WORDS/PHRASES IN BANNED LIST: {len(BANNED_TERMS):,}")
print(f"  single-word terms:  {_n_single:,} (fast set lookup)")
print(f"  multi-word phrases: {_n_phrase:,} (first-token gated)")
print(f"  punctuation terms:  {_n_punct:,} (literal regex)")
print(f"Plus {len(FORMAT_RES)} high-precision format-tell regex patterns.")
print(f"TOTAL BANNED SIGNALS: {len(BANNED_TERMS) + len(FORMAT_RES):,}")
