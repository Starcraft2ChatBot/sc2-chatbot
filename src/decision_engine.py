from __future__ import annotations

import logging
import random
import re
from typing import Any, Dict, List, Optional, Set

from rich.console import Console
from rich.status import Status

from .anti_spam import AntiSpam
from .memory import ConversationMemory
from .models import Channel, ChatMessage
from .names import memory_key, short_display_name
from .personality import build_system_prompt
from .research import research_topic, was_research_attempted
from .triggers import TriggerEngine

logger = logging.getLogger("sc2_chatbot.decision")

GAME_REQUEST_REPLIES = {
    "1v1": ["gl hf", "1v1? sure", "bet"],
    "2v2": ["I can fill", "gl"],
    "3v3": ["gl", "maybe later"],
    "4v4": ["gl"],
    "host": ["inv me", "send invite"],
    "lfg": ["what mode?"],
    "other": ["gl", "sure"],
}


def apply_blacklist(text: str, cfg: Optional[Dict[str, Any]]) -> str:
    if not text or not cfg:
        return text or ""

    out = text
    case_sensitive = bool(cfg.get("case_sensitive", False))
    flags = 0 if case_sensitive else re.IGNORECASE

    replacements = cfg.get("replacements") or {}
    if isinstance(replacements, dict):
        for src in sorted(replacements.keys(), key=lambda s: len(str(s)), reverse=True):
            dst = replacements[src]
            if src is None or src == "":
                continue
            if case_sensitive:
                out = out.replace(str(src), str(dst))
            else:
                out = re.sub(re.escape(str(src)), str(dst), out, flags=re.IGNORECASE)

    def _as_list(val: Any) -> List[str]:
        if not val:
            return []
        if isinstance(val, str):
            return [val]
        return [str(x) for x in val if x is not None and str(x) != ""]

    for sym in _as_list(cfg.get("symbols")):
        if case_sensitive:
            out = out.replace(sym, "")
        else:
            out = re.sub(re.escape(sym), "", out, flags=re.IGNORECASE)

    for letter in _as_list(cfg.get("letters")):
        if not letter:
            continue
        ch = letter[0]
        if case_sensitive:
            out = out.replace(ch, "")
        else:
            out = re.sub(re.escape(ch), "", out, flags=re.IGNORECASE)

    for sub in _as_list(cfg.get("substrings")):
        if case_sensitive:
            out = out.replace(sub, "")
        else:
            out = re.sub(re.escape(sub), "", out, flags=re.IGNORECASE)

    for word in _as_list(cfg.get("words")):
        if re.fullmatch(r"[\w']+", word, flags=re.UNICODE):
            pattern = rf"\b{re.escape(word)}\b"
        else:
            pattern = re.escape(word)
        out = re.sub(pattern, "", out, flags=flags)

    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([,.;:!?])", r"\1", out)
    return out.strip()


def _favorite_words(cfg: Optional[Dict[str, Any]]) -> List[str]:
    if not cfg:
        return []
    raw = cfg.get("words")
    if raw is None and isinstance(cfg, list):
        raw = cfg
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if not isinstance(raw, list):
        return []
    return [str(w).strip() for w in raw if w is not None and str(w).strip()]


def _normalize_compare(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _word_set(text: str) -> Set[str]:
    return set(re.findall(r"\w+", (text or "").lower()))


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / float(union) if union else 0.0


class DecisionEngine:
    def __init__(
        self,
        llm: Any,
        triggers: TriggerEngine,
        memory: ConversationMemory,
        anti_spam: AntiSpam,
        personality_state: dict,
        behaviour: dict,
        self_names: Optional[Set[str]] = None,
        blacklist: Optional[Dict[str, Any]] = None,
        favorites: Optional[Dict[str, Any]] = None,
        research: Optional[Dict[str, Any]] = None,
    ):
        self.llm = llm
        self.gemini = llm
        self.triggers = triggers
        self.memory = memory
        self.anti_spam = anti_spam
        self.state = personality_state
        self.behaviour = behaviour
        self.blacklist = blacklist or {}
        self.favorites = favorites or {}
        self.research = research or {}
        raw_selves = [n for n in (self_names or set()) if n]
        self._self_keys = {memory_key(n) for n in raw_selves}
        self._bot_display_names: List[str] = []
        seen_disp: Set[str] = set()
        for n in raw_selves:
            d = short_display_name(n) or str(n).strip()
            if d and d.lower() not in seen_disp:
                seen_disp.add(d.lower())
                self._bot_display_names.append(d)
        self._recent_bot_replies: List[str] = []
        self._recent_bot_max = 25

    def _is_own_player(self, msg: ChatMessage) -> bool:
        if msg.is_self:
            return True
        return memory_key(msg.player) in self._self_keys

    def _mentions_bot(self, msg: ChatMessage) -> bool:
        text = (msg.text or "").lower()
        for key in self._self_keys:
            if key and key in text:
                return True
        return False

    def should_consider(self, msg: ChatMessage) -> bool:
        if self.behaviour.get("ignore_self", True) and self._is_own_player(msg):
            return False
        if msg.channel == Channel.SYSTEM and self.behaviour.get("ignore_system", True):
            return False
        if self._mentions_bot(msg):
            return self.anti_spam.can_reply(msg)
        prob = float(self.behaviour.get("reply_probability", 0.9))
        if random.random() > prob:
            return False
        return self.anti_spam.can_reply(msg)

    def _store_exchange(self, incoming: ChatMessage, reply: str) -> None:
        self.memory.add(incoming)
        self.memory.add(
            ChatMessage(
                player=incoming.player,
                text=reply,
                channel=incoming.channel,
                is_self=True,
                display_name=incoming.display_name,
            )
        )
        norm = _normalize_compare(reply)
        if norm:
            self._recent_bot_replies.append(norm)
            if len(self._recent_bot_replies) > self._recent_bot_max:
                self._recent_bot_replies = self._recent_bot_replies[-self._recent_bot_max :]

    def _address_name_chance(self) -> float:
        raw = self.behaviour.get("address_by_name_chance", 0.3)
        try:
            chance = float(raw)
        except (TypeError, ValueError):
            chance = 0.3
        return max(0.0, min(1.0, chance))

    def _address_player(self, msg: ChatMessage, body: str) -> str:
        if not self.behaviour.get("address_by_name", True):
            return body
        chance = self._address_name_chance()
        if chance <= 0.0 or random.random() > chance:
            return body
        name = short_display_name(msg.display_name or msg.player)
        body = (body or "").strip()
        if not name:
            return body
        if not body:
            return name
        if re.match(re.escape(name) + r"\b", body, flags=re.IGNORECASE):
            return body
        sep = self.behaviour.get("name_separator", ", ")
        return f"{name}{sep}{body}"

    def _finalize_reply(self, msg: ChatMessage, body: str) -> Optional[str]:
        body = apply_blacklist(body or "", self.blacklist)
        if not (body or "").strip():
            return None
        reply = self._address_player(msg, body)
        reply = apply_blacklist(reply, self.blacklist)
        if not (reply or "").strip():
            return None
        return reply.strip()

    def _favorites_prompt_hint(self) -> str:
        words = _favorite_words(self.favorites)
        if not words:
            return ""
        intensity = str((self.favorites or {}).get("intensity", "medium") or "medium").lower()
        sample = ", ".join(words[:40])
        if intensity in ("strong", "high", "force"):
            return (
                f"\nStrongly prefer using these favorite words/phrases when they fit naturally "
                f"(use at least one when possible): {sample}"
            )
        if intensity in ("soft", "low", "light"):
            return f"\nWhen natural, lightly prefer vocabulary like: {sample}"
        return (
            f"\nPrefer using these favorite words/phrases often when they fit the reply "
            f"(do not force them awkwardly): {sample}"
        )

    def _is_echo(self, incoming_text: str, generated_text: str) -> bool:
        inc_raw = (incoming_text or "").strip()
        gen_raw = (generated_text or "").strip()
        if not inc_raw or not gen_raw:
            return False

        inc = _normalize_compare(inc_raw)
        gen = _normalize_compare(gen_raw)
        if not inc or not gen:
            return False

        if gen == inc:
            return True
        if len(inc) >= 6 and inc in gen:
            return True
        if len(gen) >= 6 and gen in inc:
            return True

        if len(inc) >= 12 and len(gen) >= 8:
            for size in (16, 12, 10, 8):
                if len(inc) < size:
                    continue
                for i in range(0, len(inc) - size + 1):
                    chunk = inc[i : i + size]
                    if " " in chunk and chunk in gen:
                        return True

        inc_tokens = re.findall(r"\w+", inc)
        gen_tokens = re.findall(r"\w+", gen)
        if not inc_tokens or not gen_tokens:
            return False

        inc_words = set(inc_tokens)
        gen_words = set(gen_tokens)

        if len(gen_tokens) >= 2:
            from_player = sum(1 for w in gen_tokens if w in inc_words)
            ratio_from_player = from_player / float(len(gen_tokens))
            if len(gen_tokens) <= 6 and ratio_from_player >= 0.55:
                return True
            if len(gen_tokens) > 6 and ratio_from_player >= 0.50:
                return True

        if len(inc_words) >= 3:
            overlap = inc_words.intersection(gen_words)
            if len(overlap) / float(len(inc_words)) >= 0.55:
                return True
            if _jaccard(inc_words, gen_words) >= 0.55:
                return True

        if len(inc_tokens) >= 3 and len(gen_tokens) >= 3:
            gen_ngrams = set()
            for n in (4, 3):
                if len(gen_tokens) < n:
                    continue
                for i in range(len(gen_tokens) - n + 1):
                    gen_ngrams.add(tuple(gen_tokens[i : i + n]))
            for n in (4, 3):
                if len(inc_tokens) < n:
                    continue
                for i in range(len(inc_tokens) - n + 1):
                    if tuple(inc_tokens[i : i + n]) in gen_ngrams:
                        return True

        if len(inc_tokens) >= 4 and len(gen_tokens) >= 3:
            common = {
                "you", "the", "a", "an", "is", "are", "to", "and", "or", "of",
                "in", "it", "that", "this", "i", "im", "me", "my", "your", "u",
                "ur", "lol", "bro", "yeah", "nah", "ok", "okay", "just", "so",
            }
            gen_bigrams = set()
            for i in range(len(gen_tokens) - 1):
                gen_bigrams.add((gen_tokens[i], gen_tokens[i + 1]))
            hits = 0
            for i in range(len(inc_tokens) - 1):
                pair = (inc_tokens[i], inc_tokens[i + 1])
                if pair[0] in common and pair[1] in common:
                    continue
                if pair in gen_bigrams:
                    hits += 1
            if hits >= 2:
                return True

        return False

    def _is_research_echo(self, generated_text: str, research_brief: str) -> bool:
        if not generated_text or not research_brief:
            return False

        source_lines = []
        for line in research_brief.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("[RESEARCH BRIEF"):
                continue
            if re.match(r"^Source \d+ \(.+\):$", s):
                continue
            source_lines.append(s)

        if not source_lines:
            return False

        gen = _normalize_compare(generated_text)
        if not gen:
            return False

        gen_tokens = re.findall(r"\w+", gen)
        if len(gen_tokens) < 4:
            return False

        for src in source_lines:
            src_n = _normalize_compare(src)
            if not src_n:
                continue

            if len(src_n) >= 20 and (src_n in gen or gen in src_n):
                return True

            src_tokens = re.findall(r"\w+", src_n)
            if len(src_tokens) < 6 or len(gen_tokens) < 6:
                continue
            src_ngrams = set()
            for n in (8, 6):
                if len(src_tokens) < n:
                    continue
                for i in range(len(src_tokens) - n + 1):
                    src_ngrams.add(tuple(src_tokens[i : i + n]))
            for n in (8, 6):
                if len(gen_tokens) < n:
                    continue
                for i in range(len(gen_tokens) - n + 1):
                    if tuple(gen_tokens[i : i + n]) in src_ngrams:
                        return True

            src_words = _word_set(src_n)
            gen_words = _word_set(gen)
            if len(src_words) >= 5 and len(gen_words) >= 3:
                if _jaccard(src_words, gen_words) >= 0.80:
                    return True

        return False

    def _recent_self_replies(self, player: str, limit: int = 12) -> List[str]:
        out: List[str] = []
        seen: Set[str] = set()
        try:
            ctx = self.memory.get_context(player) or []
        except Exception:
            ctx = []
        for h in reversed(ctx):
            if getattr(h, "is_self", False):
                t = (h.text or "").strip()
                n = _normalize_compare(t)
                if t and n and n not in seen:
                    seen.add(n)
                    out.append(t)
                if len(out) >= limit:
                    break
        for n in reversed(self._recent_bot_replies):
            if n and n not in seen:
                seen.add(n)
                out.append(n)
            if len(out) >= limit + 8:
                break
        return out

    def _is_self_repeat(self, generated_text: str, player: str) -> bool:
        gen = _normalize_compare(generated_text)
        if not gen or len(gen) < 4:
            return False
        gen_words = _word_set(gen)
        for prev in self._recent_self_replies(player, limit=15):
            prev_n = _normalize_compare(prev)
            if not prev_n:
                continue
            if gen == prev_n:
                return True
            if len(gen) >= 10 and (gen in prev_n or prev_n in gen):
                return True
            prev_words = _word_set(prev_n)
            if len(gen_words) >= 3 and len(prev_words) >= 3:
                if _jaccard(gen_words, prev_words) >= 0.78:
                    return True
                inter = gen_words & prev_words
                if len(inter) >= 4 and len(inter) / float(max(len(gen_words), 1)) >= 0.85:
                    return True
        return False

    def _previous_replies_hint(self, player: str) -> str:
        recent = self._recent_self_replies(player, limit=6)
        if not recent:
            return ""
        bits = []
        for t in recent[:5]:
            s = (t or "").strip().replace("\n", " ")
            if len(s) > 60:
                s = s[:57] + "..."
            bits.append(f'"{s}"')
        return (
            "\nDo NOT reuse or closely rephrase any of your recent replies: "
            + "; ".join(bits)
            + ". Say something new."
        )

    def decide_and_generate(self, msg: ChatMessage) -> Optional[str]:
        if not self.should_consider(msg):
            return None

        label = short_display_name(msg.display_name or msg.player)

        canned = self.triggers.check(msg, self.state["aggressiveness"])
        if canned:
            if self._is_self_repeat(canned, msg.player):
                logger.info("Canned reply matched recent self-reply — skipping canned")
            else:
                reply = self._finalize_reply(msg, canned)
                if not reply:
                    return None
                if self._is_self_repeat(reply, msg.player):
                    logger.info("Canned reply still self-repeat after finalize — skipping")
                else:
                    self.anti_spam.record_reply(msg.player)
                    self._store_exchange(msg, reply)
                    return reply

        if msg.is_game_request and self.behaviour.get("reply_to_game_requests", True):
            if self.behaviour.get("game_request_use_canned", False):
                pool = GAME_REQUEST_REPLIES.get(msg.game_request_kind) or GAME_REQUEST_REPLIES["other"]
                choice = random.choice(pool)
                if not self._is_self_repeat(choice, msg.player):
                    reply = self._finalize_reply(msg, choice)
                    if reply and not self._is_self_repeat(reply, msg.player):
                        self.anti_spam.record_reply(msg.player)
                        self._store_exchange(msg, reply)
                        return reply

        mentioned = self._mentions_bot(msg)
        system = build_system_prompt(
            aggressiveness=self.state["aggressiveness"],
            political_mode=self.state.get("political_mode", "neutral"),
            response_length=self.state["response_length"],
            emoji_intensity=self.state.get("emoji_intensity", 0),
            topics=self.state.get("topics", {}),
            channel=msg.channel.value,
            player_name=label,
            sc2_reference_level=int(self.state.get("sc2_reference_level", 2)),
            custom_enabled=bool(self.state.get("custom_enabled", False)),
            custom_prompt=str(self.state.get("custom_prompt") or ""),
            bot_names=list(self._bot_display_names),
            bot_mentioned=mentioned,
        )

        extra = ""
        if mentioned:
            names = ", ".join(self._bot_display_names[:6]) or "your name"
            extra += (
                f"\nThey mentioned YOU ({names}). "
                "They are talking to/about you — respond as yourself in character. "
                "Do not treat that name as another player. Do not attack yourself."
            )
        if msg.is_game_request:
            extra += f"\nLooks like a lobby/game request ({msg.game_request_kind or 'other'})."

        banned_hint_parts: List[str] = []
        for key in ("symbols", "words", "substrings"):
            items = self.blacklist.get(key) or []
            if isinstance(items, list) and items:
                sample = ", ".join(repr(x) for x in items[:12])
                banned_hint_parts.append(f"{key}: {sample}")
        if banned_hint_parts:
            extra += (
                "\nDo not use these banned characters/words in your reply: "
                + "; ".join(banned_hint_parts)
            )

        extra += self._favorites_prompt_hint()
        extra += self._previous_replies_hint(msg.player)
        extra += (
            "\nNever repeat yourself. Never copy, quote, or rephrase large parts of what they said. "
            "Do not paste their words back at them (even partially). "
            "React with your own new wording only. Each reply must be a fresh reaction."
        )

        ctx = self.memory.get_context(msg.player) or []

        history = []
        for h in ctx[-10:]:
            role = "user" if not h.is_self else "model"
            history.append({"role": role, "parts": [h.text]})

        player_history_texts: List[str] = []
        bot_history_texts: List[str] = []
        for h in ctx[-15:]:
            if h.is_self:
                bot_history_texts.append(h.text or "")
            else:
                player_history_texts.append(h.text or "")

        research_brief = ""
        try:
            research_brief = research_topic(
                msg.text or "",
                self.research,
                player=msg.player,
                history_texts=player_history_texts,
                bot_history_texts=bot_history_texts,
            )
        except Exception:
            logger.exception("Research failed")
            research_brief = ""

        research_was_attempted = False
        try:
            research_was_attempted = was_research_attempted(
                msg.text or "",
                self.research,
                history_texts=player_history_texts,
                bot_history_texts=bot_history_texts,
            )
        except Exception:
            pass

        if research_brief:
            extra += (
                "\nRESEARCH BRIEF — this is reference material, NOT something to paste. "
                "Read it, understand it, then speak as yourself.\n"
                "Rules for using research:\n"
                "  - Paraphrase everything in your own voice. Never quote whole sentences.\n"
                "  - Do not mention 'Wikipedia', 'sources', 'research', or 'I looked it up'.\n"
                "  - Only use the parts that actually answer the current conversation.\n"
                "  - If the brief is off-topic or does not help, ignore it completely.\n"
                "  - If the brief contradicts what you already said, prefer the brief but "
                "stay in character — do not announce that you were wrong.\n"
                "  - Keep your normal short, casual chat style.\n"
                "--- BEGIN RESEARCH ---\n"
                + research_brief
                + "\n--- END RESEARCH ---"
            )
        elif research_was_attempted:
            extra += (
                "\nCRITICAL: You tried to look this up but found NO reliable information. "
                "Do NOT invent facts. Do NOT make up dates, events, deaths, or claims. "
                "If you cannot answer factually, say something short like 'i cant find that' "
                "or 'no idea' or change the subject. Never pretend to know something you don't."
            )

        user_prompt = (
            f"Player '{label}' said:\n\"{msg.text}\"\n\n"
            f"Write one in-character chat reply.{extra}"
        )

        with Status(
            "[cyan]AI generating reply…[/cyan]",
            console=Console(stderr=True),
            spinner="dots",
        ):
            body = self.llm.generate(system, user_prompt, history)

        def _needs_rewrite(text: str) -> str:
            if not (text or "").strip():
                return ""
            if self._is_echo(msg.text, text):
                return "echo"
            if self._is_self_repeat(text, msg.player):
                return "self_repeat"
            if self._is_research_echo(text, research_brief):
                return "research_echo"
            return ""

        reason = _needs_rewrite(body or "")
        if reason:
            logger.warning(
                "LLM reply rejected (%s): %r — requesting rewrite",
                reason,
                (body or "")[:80],
            )
            rewrite_prompt = (
                f"{user_prompt}\n\n"
                f"CRITICAL: Your previous draft was invalid ({reason}). "
                f"Draft was: {(body or '')[:120]!r}. "
                "Write a completely NEW short chat reply in your own words. "
                "Do not echo, quote, or reuse phrases from the player's message. "
                "Do not reuse your own recent lines. "
                "Do not copy sentences from the research brief — paraphrase only. "
                "Fresh wording only."
            )
            with Status(
                "[cyan]AI rewriting response…[/cyan]",
                console=Console(stderr=True),
                spinner="dots",
            ):
                body = self.llm.generate(system, rewrite_prompt, history)

            reason2 = _needs_rewrite(body or "")
            if reason2:
                logger.warning(
                    "Rewrite still invalid (%s) — dropping response: %r",
                    reason2,
                    (body or "")[:80],
                )
                return None

        if not (body or "").strip():
            logger.info("LLM returned empty — not sending a reply")
            return None

        if random.random() < self.behaviour.get("typo_chance", 0.0):
            body = self._introduce_typo(body)

        body = body.strip().strip('"').strip("'")
        body = re.sub(
            r"^\[?\d*\.?\s*(?:General|Arcade|Co-?op|All|Team|Whisper)\]?\s*",
            "",
            body,
            flags=re.I,
        ).strip()

        if not body:
            logger.info("Reply empty after cleanup — not sending")
            return None

        if (
            self._is_echo(msg.text, body)
            or self._is_self_repeat(body, msg.player)
            or self._is_research_echo(body, research_brief)
        ):
            logger.info("Reply still echo/self-repeat/research-echo after cleanup — not sending")
            return None

        reply = self._finalize_reply(msg, body)
        if not reply:
            logger.info("Reply empty after blacklist — not sending")
            return None

        if (
            self._is_echo(msg.text, reply)
            or self._is_self_repeat(reply, msg.player)
            or self._is_research_echo(reply, research_brief)
        ):
            logger.info("Final reply echo/self-repeat/research-echo — not sending")
            return None

        self.anti_spam.record_reply(msg.player)
        self._store_exchange(msg, reply)
        return reply

    @staticmethod
    def _introduce_typo(text: str) -> str:
        if len(text) < 4:
            return text
        i = random.randint(1, len(text) - 2)
        chars = list(text)
        if random.random() < 0.5:
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        else:
            chars.pop(i)
        return "".join(chars)