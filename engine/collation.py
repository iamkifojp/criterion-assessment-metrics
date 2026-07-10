"""Gojūon (Japanese あいうえお) collation for roster names.

Google Classroom exports student names in romaji ("Surname Given"), and the
list arrives ordered by the Latin spelling. A Japanese classroom register,
however, is ordered by the *gojūon* reading of the name — and romaji
alphabetical order is NOT the same as gojūon order (alphabetically ``Sato``
sorts before ``Kato``; in gojūon か precedes さ, so it is the other way round).

This module converts a romaji string to a sequence of kana "mora" sort keys so
a roster can be ordered the way a Japanese teacher expects. The reader is a
pragmatic Hepburn/Kunrei mapping: it is exact for ordinary Japanese readings
and degrades gracefully on foreign names (which a teacher can still nudge with
the ↑/↓ buttons). Each mora becomes a ``(row, vowel, voicing)`` tuple, so
comparing the resulting lists yields gojūon order:

    row     0 あ(vowel) 1 か 2 さ 3 た 4 な 5 は 6 ま 7 や 8 ら 9 わ 10 ん
    vowel   a=0 i=1 u=2 e=3 o=4
    voicing 0 plain   1 dakuten(゛)   2 handakuten(゜)

Vowel outranks voicing so か→が→き→ぎ interleave as they do in a dictionary
(は ば ぱ ひ び ぴ ...).
"""

from typing import List, Tuple

MoraKey = Tuple[int, int, int]

_VOWELS = {"a": 0, "i": 1, "u": 2, "e": 3, "o": 4}

# Single consonant onset -> (row, voicing). ``l``/``v`` are best-effort
# approximations for foreign names (l→ra-row, v→ba-row).
_ONSET = {
    "k": (1, 0), "g": (1, 1),
    "s": (2, 0), "z": (2, 1),
    "t": (3, 0), "d": (3, 1),
    "n": (4, 0),
    "h": (5, 0), "f": (5, 0), "b": (5, 1), "p": (5, 2),
    "m": (6, 0),
    "y": (7, 0),
    "r": (8, 0), "l": (8, 0),
    "w": (9, 0), "v": (5, 1),
}


def gojuon_sort_key(text: str) -> List[MoraKey]:
    """Convert a romaji name to a list of gojūon mora keys.

    The list can be compared directly with ``<`` to order names in あいうえお
    order. Non-letters are ignored; an empty/unreadable string yields ``[]``
    (which sorts first).
    """
    s = "".join(ch for ch in (text or "").lower() if ch.isalpha())
    keys: List[MoraKey] = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]

        # Sokuon (っ): a doubled *consonant* — approximate by dropping the
        # first copy. ``n`` and ``y`` are excluded (nn = ん+な, y is a glide).
        if c not in "aeiouyn" and i + 1 < n and s[i + 1] == c:
            i += 1
            continue

        two = s[i:i + 2]

        # し / ち families, incl. palatal しゃ しゅ しょ / ちゃ ちゅ ちょ.
        if two in ("sh", "ch"):
            row, voic = (2, 0) if two == "sh" else (3, 0)
            j = i + 2
            v = s[j] if j < n else ""
            if v in "auo":                       # しゃ/しゅ/しょ = し + small ya
                keys.append((row, 1, voic))
                keys.append((7, _VOWELS[v], 0))
                i = j + 1
            elif v in "ie":                      # し / しぇ
                keys.append((row, _VOWELS[v], voic))
                i = j + 1
            else:                                # bare 'sh'/'ch' -> し/ち
                keys.append((row, 1, voic))
                i = j
            continue

        # つ (and rare foreign tsa/tse/tso).
        if two == "ts":
            j = i + 2
            v = s[j] if j < n else ""
            if v in _VOWELS:
                keys.append((3, _VOWELS[v], 0))
                i = j + 1
            else:
                keys.append((3, 2, 0))           # つ
                i = j
            continue

        # Palatal glide: consonant + y + a/u/o (kya, gyo, ryu, ...).
        if c in _ONSET and i + 1 < n and s[i + 1] == "y" \
                and i + 2 < n and s[i + 2] in "auo":
            row, voic = _ONSET[c]
            keys.append((row, 1, voic))          # base i-column kana
            keys.append((7, _VOWELS[s[i + 2]], 0))
            i += 3
            continue

        # じ / じゃ じゅ じょ.
        if c == "j":
            j = i + 1
            v = s[j] if j < n else ""
            if v in "auo":
                keys.append((2, 1, 1))
                keys.append((7, _VOWELS[v], 0))
                i = j + 1
            elif v in "ie":
                keys.append((2, _VOWELS[v], 1))
                i = j + 1
            else:
                keys.append((2, 1, 1))
                i = j
            continue

        # Hard/soft 'c' for foreign spellings: co/ca/cu -> か-row, ce/ci -> さ-row.
        if c == "c":
            j = i + 1
            v = s[j] if j < n else ""
            if v in "aou":
                keys.append((1, _VOWELS[v], 0))
                i = j + 1
            elif v in "ie":
                keys.append((2, _VOWELS[v], 0))
                i = j + 1
            else:
                keys.append((1, 4, 0))           # lone 'c' -> こ-ish
                i = j
            continue

        # Ordinary consonant + vowel.
        if c in _ONSET:
            j = i + 1
            v = s[j] if j < n else ""
            if v in _VOWELS:
                row, voic = _ONSET[c]
                keys.append((row, _VOWELS[v], voic))
                i = j + 1
            elif c == "n":
                keys.append((10, 0, 0))          # syllabic ん
                i = j
            else:
                i = j                            # stray consonant: skip
            continue

        # Bare vowel.
        if c in _VOWELS:
            keys.append((0, _VOWELS[c], 0))
            i += 1
            continue

        i += 1                                    # q/x/etc.: skip
    return keys
