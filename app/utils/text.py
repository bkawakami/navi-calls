"""Utilitários de texto: normalização e detecção do chamado "Navi"."""
import re
import unicodedata
from typing import Iterable, Optional, Tuple

# Pedidos de anotação. Aplicados sobre o texto "dobrado" (minúsculas, sem acentos),
# por isso as alternativas aparecem sem acento.
REMEMBER_PATTERNS = [
    r"lembre[\s-]*se\s+(?:de\s+|que\s+)?",
    r"lembra(?:-se)?\s+(?:de\s+|que\s+)?",
    r"nao\s+(?:se\s+)?esque[cç]a\s+(?:de\s+|que\s+)?",
    r"nao\s+esquece\s+(?:de\s+|que\s+)?",
    r"anot[ae]\s+(?:ai[:,]?\s+|que\s+|isso[:,]?\s+)?",
    r"registr[ae]\s+(?:ai[:,]?\s+|que\s+|isso[:,]?\s+)?",
    r"guard[ae]\s+(?:ai[:,]?\s+|que\s+|isso[:,]?\s+)?",
    r"tom[ae]\s+nota\s+(?:de\s+|que\s+)?",
    r"salv[ae]\s+(?:ai[:,]?\s+|que\s+|isso[:,]?\s+)?",
]

MIN_REQUEST_WORDS = 3
# A wake word só conta como chamado se estiver no começo (vocativo) ou no fim da frase.
# Menções no meio ("fala com a Navi depois") são tratadas como conversa sobre a Navi.
WAKE_HEAD_WORDS = 3
WAKE_TAIL_WORDS = 2
# Artigo/preposição antes do nome indica menção em terceira pessoa ("fala com a Navi"), não vocativo.
THIRD_PERSON_BEFORE = re.compile(r"(?:^|\s)(?:a|as|o|da|do|na|no|pra|pro|pela|pelo|com a|para a|que a|e a|ou a|essa|esta|aquela)\s+$")


def fold(text: str) -> str:
    """Minúsculas sem acentos preservando o comprimento (1 caractere -> 1 caractere)."""
    out = []
    for ch in text or "":
        base = "".join(c for c in unicodedata.normalize("NFD", ch) if unicodedata.category(c) != "Mn")
        out.append((base or ch).lower()[:1] or ch)
    return "".join(out)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", fold(text)).strip()


def _wake_pattern(wake_words: Iterable[str]) -> str:
    words = [normalize(w) for w in wake_words if w and w.strip()]
    return r"(?<![\w])(" + "|".join(re.escape(w) for w in words) + r")(?![\w])"


def find_wake_word(text: str, wake_words: Iterable[str], positional: bool = True) -> Optional[Tuple[int, int]]:
    """(início, fim) da wake word no texto original (índices válidos no original).

    Com positional=True, só considera ocorrências nas primeiras WAKE_HEAD_WORDS palavras
    ou nas últimas WAKE_TAIL_WORDS palavras da frase.
    """
    folded = fold(text)
    total_words = len(re.findall(r"\S+", folded))
    for m in re.finditer(_wake_pattern(wake_words), folded):
        if not positional:
            return (m.start(), m.end())
        before = folded[: m.start()]
        if THIRD_PERSON_BEFORE.search(before):
            continue
        word_index = len(re.findall(r"\S+", before))
        if word_index < WAKE_HEAD_WORDS or word_index >= total_words - WAKE_TAIL_WORDS:
            return (m.start(), m.end())
    return None


def extract_request(text: str, wake_words: Iterable[str]) -> Optional[str]:
    """Texto do pedido após a wake word. Se não houver nada depois, devolve o texto completo."""
    span = find_wake_word(text, wake_words)
    if not span:
        return None
    after = text[span[1]:].lstrip(" ,.!?:;-–—")
    return after.strip() if after.strip() else text.strip()


def request_is_complete(request_text: str) -> bool:
    """Heurística: pedido com poucas palavras provavelmente ainda não terminou ("Navi, ...")."""
    words = [w for w in re.split(r"\s+", request_text.strip()) if w]
    return len(words) >= MIN_REQUEST_WORDS


def extract_note(request_text: str) -> Optional[str]:
    """Se o pedido for para lembrar/anotar algo, devolve o conteúdo da nota (texto original)."""
    folded = fold(request_text)
    for pat in REMEMBER_PATTERNS:
        m = re.search(r"(?:^|(?<![\w]))(?:por favor,?\s+)?" + pat, folded)
        if m:
            note = request_text[m.end():].strip(" .!?,;:")
            if note:
                return note
    return None
