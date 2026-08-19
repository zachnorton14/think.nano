"""
Prompt rendering and request validation for the hosted service.

This is a port of `build_conversation_tokens` / `validate_chat_request` from
scripts/chat_web.py, decoupled from that script's module-level argparse globals
(importing chat_web.py parses sys.argv, which blows up under uvicorn/Beam).

The two copies must agree on the chat template or the hosted model will see a
prompt format it was never trained on. If you change the template in one, change
it in the other -- or lift this module into nanochat/ and have chat_web.py
import it, which is the better long-term fix.

The user-turn shaping (punctuation repair, priming turns) is NOT duplicated: it
lives in nanochat/prompt_shaping.py, which both copies import.
"""

# Abuse-prevention limits, matching scripts/chat_web.py.
MAX_MESSAGES_PER_REQUEST = 500
MAX_MESSAGE_LENGTH = 8000
MAX_TOTAL_CONVERSATION_LENGTH = 32000
MIN_TEMPERATURE, MAX_TEMPERATURE = 0.0, 2.0
MIN_TOP_K, MAX_TOP_K = 0, 200
MIN_MAX_TOKENS, MAX_MAX_TOKENS = 1, 4096
MIN_REPETITION_PENALTY, MAX_REPETITION_PENALTY = 1.0, 2.0

# Headroom left over after the prompt plus the tokens we are about to generate,
# so rounding in the budget math can never push us past the trained context.
CONTEXT_SAFETY_MARGIN = 16


from nanochat.prompt_shaping import repair_messages


class ValidationError(ValueError):
    """Raised for a malformed request; the caller maps this to HTTP 400."""


def validate_messages(messages):
    """Validate a list of {"role", "content"} dicts. Raises ValidationError."""
    if not messages:
        raise ValidationError("At least one message is required")
    if len(messages) > MAX_MESSAGES_PER_REQUEST:
        raise ValidationError(f"Too many messages. Maximum {MAX_MESSAGES_PER_REQUEST} allowed per request")

    total_length = 0
    for i, message in enumerate(messages):
        content = message.get("content")
        if not content:
            raise ValidationError(f"Message {i} has empty content")
        if len(content) > MAX_MESSAGE_LENGTH:
            raise ValidationError(f"Message {i} is too long. Maximum {MAX_MESSAGE_LENGTH} characters per message")
        total_length += len(content)
    if total_length > MAX_TOTAL_CONVERSATION_LENGTH:
        raise ValidationError(f"Total conversation is too long. Maximum {MAX_TOTAL_CONVERSATION_LENGTH} characters")

    # A system message is allowed, but only first: the tokenizer has no system
    # special token and renders one by merging it into the first user turn.
    for i, message in enumerate(messages):
        role = message.get("role")
        if role == "system":
            if i != 0:
                raise ValidationError("Only the first message may have role 'system'")
            continue
        if role not in ("user", "assistant"):
            raise ValidationError(f"Message {i} has invalid role. Must be 'user', 'assistant', or 'system'")
    if messages[0].get("role") == "system" and len(messages) < 2:
        raise ValidationError("A system message must be followed by a user message")


def validate_sampling(temperature=None, top_k=None, max_tokens=None, repetition_penalty=None):
    """Range-check the sampling knobs. Raises ValidationError."""
    checks = (
        ("temperature", temperature, MIN_TEMPERATURE, MAX_TEMPERATURE),
        ("top_k", top_k, MIN_TOP_K, MAX_TOP_K),
        ("max_tokens", max_tokens, MIN_MAX_TOKENS, MAX_MAX_TOKENS),
        ("repetition_penalty", repetition_penalty, MIN_REPETITION_PENALTY, MAX_REPETITION_PENALTY),
    )
    for name, value, low, high in checks:
        if value is not None and not (low <= value <= high):
            raise ValidationError(f"{name} must be between {low} and {high}")


def render_conversation_tokens(tokenizer, sequence_len, messages, max_new_tokens,
                               default_system_prompt="", priming_turns=(),
                               fix_punctuation=False, log=None):
    """Render the chat history into prompt tokens, primed for the assistant.

    Mirrors Tokenizer.render_conversation's convention: this tokenizer has no
    system special token (the vocab slots went to BPE merges), so a leading
    system message is merged into the first user turn with a blank line between.
    Training does exactly this, so serving must too.

    When the history outgrows the model's context we drop whole user/assistant
    exchanges from the front. The system prompt and `priming_turns` are standing
    context, not history, so they survive eviction; the system prompt is
    re-merged into whichever user turn ends up first.

    `fix_punctuation` repairs each visitor turn before tokenizing (missing
    terminal mark, leading capital) and `priming_turns` splices an invisible
    opening exchange in front of the conversation. Both target the same failure
    -- unpunctuated input is thin in SFT -- from opposite ends; see
    nanochat/prompt_shaping.py.
    """
    bos = tokenizer.get_bos_token_id()
    user_start = tokenizer.encode_special("<|user_start|>")
    user_end = tokenizer.encode_special("<|user_end|>")
    assistant_start = tokenizer.encode_special("<|assistant_start|>")
    assistant_end = tokenizer.encode_special("<|assistant_end|>")

    turns = list(messages)
    system_text = default_system_prompt
    if turns and turns[0].get("role") == "system":
        system_text = turns[0]["content"].strip()  # per-request prompt wins
        turns = turns[1:]
    if fix_punctuation:
        turns = repair_messages(turns)
    # Never repaired: the priming user turn is unpunctuated on purpose.
    priming = list(priming_turns)

    # Overrunning the trained context does not raise: the rotary cache is built
    # 10x oversized (gpt.py) and the KV cache is sized per request, so the model
    # would just generate from positions it never saw in training and quietly
    # produce mush. The character limits above do not protect us either (32K
    # chars is roughly 2x a 4096-token context), so budget it explicitly.
    budget = sequence_len - max_new_tokens - CONTEXT_SAFETY_MARGIN

    def render(turns):
        out = [bos]
        for i, message in enumerate([*priming, *turns]):
            content = message["content"]
            if i == 0 and system_text and message["role"] == "user":
                content = f"{system_text}\n\n{content}"
            start, end = (user_start, user_end) if message["role"] == "user" else (assistant_start, assistant_end)
            out.append(start)
            out.extend(tokenizer.encode(content))
            out.append(end)
        out.append(assistant_start)  # prime the assistant for completion
        return out

    dropped = 0
    while len(turns) > 1:
        tokens = render(turns)
        if len(tokens) <= budget:
            if dropped and log:
                log(f"Context budget: dropped {dropped} oldest message(s), kept system prompt")
            return tokens
        turns = turns[2:]  # drop an exchange, keeping user/assistant alternation
        dropped += 2

    # A single turn that still overflows: keep the system prompt intact and clip
    # the visitor's own text, since that is the part we can afford to lose.
    tokens = render(turns)
    if len(tokens) <= budget:
        return tokens
    # Drop the priming turns before clipping the visitor's own words: an example
    # of good style is worth less than the question the visitor actually asked.
    message = turns[0]
    prefix = f"{system_text}\n\n" if system_text and message["role"] == "user" else ""
    prefix_ids = tokenizer.encode(prefix) if prefix else []
    room = max(budget - len(prefix_ids) - 4, 0)  # bos + start + end + assistant_start
    body = tokenizer.encode(message["content"])[:room]
    if log:
        log(f"Context budget: single message clipped to {len(body)} tokens")
    return [bos, user_start, *prefix_ids, *body, user_end, assistant_start]
