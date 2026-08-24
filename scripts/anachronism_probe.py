"""
Anachronism probe: a labeled fixture for the go/no-go separation test that checks
whether the vintage base model's per-token loss can distinguish authentic pre-1930s
questions from anachronistic ones.

Two buckets:
  - authentic:     real opening questions drawn from the AuthenticPre1930 SFT set
                   (tasks/authentic-pre1930.py) — genuine pre-1930s phrasing.
  - anachronistic: hand-authored questions that violate the period in one of three
                   ways, used to probe what loss can and cannot catch:
                     lexical    - contains post-1930 vocabulary (television, DNA, ...)
                                  expected: easy to catch (tokens the corpus never saw)
                     conceptual - period-safe words, modern concept or settled framing
                                  expected: partially caught
                     register   - period-safe topic, modern casual / meta phrasing
                                  expected: the hard case; may not separate at all

This is a fixture, not a training Task: it exposes plain question strings for scoring.
"""

from importlib import import_module

AuthenticPre1930 = import_module("tasks.authentic-pre1930").AuthenticPre1930

# Authored anachronistic probes. `kind` lets the separation test report which failure
# modes the loss signal catches, so a null result is still diagnostic rather than opaque.
ANACHRONISTIC = [
    # --- lexical: post-1930 vocabulary the pretrain corpus never contained ---
    {"kind": "lexical", "q": "How does a television receiver form its picture?"},
    {"kind": "lexical", "q": "What is the function of a transistor in a computer?"},
    {"kind": "lexical", "q": "How do antibiotics such as penicillin cure infection?"},
    {"kind": "lexical", "q": "What powers a jet airliner at cruising altitude?"},
    {"kind": "lexical", "q": "How does DNA store the genetic code?"},
    {"kind": "lexical", "q": "What is the purpose of a nuclear reactor's control rods?"},
    {"kind": "lexical", "q": "How does a smartphone connect to the internet over Wi-Fi?"},
    {"kind": "lexical", "q": "What does a vaccine's mRNA instruct the cell to do?"},
    {"kind": "lexical", "q": "How is a laser beam kept coherent?"},
    {"kind": "lexical", "q": "What did radar contribute to air defense?"},
    {"kind": "lexical", "q": "How are plastics synthesized from petroleum?"},
    {"kind": "lexical", "q": "What training does an astronaut undergo for spaceflight?"},
    {"kind": "lexical", "q": "How does a microwave oven heat food?"},
    {"kind": "lexical", "q": "What is stored on a compact disc?"},
    {"kind": "lexical", "q": "How does an electric car recharge its battery?"},
    # --- conceptual: period-plausible words, modern concept or settled framing ---
    {"kind": "conceptual", "q": "How does the Big Bang account for the origin of the universe?"},
    {"kind": "conceptual", "q": "What evidence shows that the continents drift across the globe?"},
    {"kind": "conceptual", "q": "How does relativity alter our notion of simultaneous events?"},
    {"kind": "conceptual", "q": "Why do all living creatures share a single common ancestor?"},
    {"kind": "conceptual", "q": "What caused the Second World War to break out in Europe?"},
    {"kind": "conceptual", "q": "How did the Cold War divide the great powers?"},
    {"kind": "conceptual", "q": "What did the first landing of men upon the Moon achieve?"},
    {"kind": "conceptual", "q": "How does the uncertainty principle limit measurement?"},
    {"kind": "conceptual", "q": "What does a nation's gross domestic product measure?"},
    {"kind": "conceptual", "q": "How do genes carry inherited traits between generations?"},
    {"kind": "conceptual", "q": "What holds a galaxy together across such vast distances?"},
    # --- register: period-safe topic, modern casual / meta phrasing ---
    {"kind": "register", "q": "Can you give me a quick summary of how rainfall is formed?"},
    {"kind": "register", "q": "What's the deal with the trade winds, exactly?"},
    {"kind": "register", "q": "What are the key takeaways about the causes of the tides?"},
    {"kind": "register", "q": "TL;DR: why does iron rust?"},
    {"kind": "register", "q": "Break down for me how a lever multiplies force."},
    {"kind": "register", "q": "So how does a steam engine actually work, step by step?"},
    {"kind": "register", "q": "Give me the top three reasons the seasons change."},
    {"kind": "register", "q": "Walk me through how the heart circulates the blood."},
    {"kind": "register", "q": "What's the bottom line on why the sky is blue?"},
    {"kind": "register", "q": "Any tips for remembering the order of the planets?"},
]


def load_anachronistic_questions():
    """Return the authored anachronistic probe questions as a list of {'kind', 'q'} dicts."""
    return list(ANACHRONISTIC)


def load_authentic_questions(n=256, split="test", val_size=256):
    """
    Return up to n authentic opening questions (the first user turn) from the
    AuthenticPre1930 SFT set. Defaults to the held-out 'test' split so the probe
    does not overlap whatever split was used for SFT training.
    """
    task = AuthenticPre1930(split=split, val_size=val_size)
    questions = []
    for i in range(min(n, len(task))):
        for m in task[i]["messages"]:
            if m["role"] == "user":
                questions.append(m["content"])
                break
    return questions
