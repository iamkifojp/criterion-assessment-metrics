"""Conservative roster matching for copied Drive files and local submissions.

No I/O: student data is supplied by CAM at runtime. Partial names and spelling
similarity never assign a student automatically.
"""

import re
import unicodedata


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


def contains(text, value):
    value = normalize(value)
    return bool(value) and f" {value} " in f" {normalize(text)} "


def name_variants(entry):
    name = normalize(entry.get("name"))
    first = normalize(entry.get("first"))
    variants = {name} if len(name.split()) >= 2 else set()
    if first and name.endswith(" " + first):
        last = name[:-len(first)].strip()
        variants.add(first + " " + last)
    return variants


def unmatched_identity(file):
    # IDs, rather than filename alone, keep identically named unnamed files
    # separate. This key also travels through CAM's durable manual work aliases.
    return f"Unmatched {file['id']}: {file.get('name') or '(unnamed)'}"


def has_shortened_school_ids(roster):
    """Detect rosters stored by the former digit-only email parser."""
    for entry in roster:
        local = str(entry.get("email") or "").split("@", 1)[0].strip()
        if len(re.findall(r"\d+", local)) > 1 and entry.get("key") != local:
            return True
    return False


def match_submission(file, roster, aliases=None):
    """Return (roster entry or None, reason) using only unique exact evidence.

    Drive owner email must be on this roster. Other sharing/editing identities
    are hints; multiple roster candidates or conflicting filenames need review.
    A manual CAM alias takes precedence over automatic evidence.
    """
    entries = {e["key"]: e for e in roster if isinstance(e, dict) and e.get("key")}
    alias_keys = [unmatched_identity(file), file.get("local_student", "")]
    manual = {(aliases or {}).get(k) for k in alias_keys if k}
    manual &= entries.keys()
    if len(manual) == 1:
        return entries[next(iter(manual))], "manual"
    if manual:
        return None, "ambiguous"

    text = file.get("name", "")
    # Local folders may supply a student name/ID even if filenames are unnamed.
    local = file.get("local_student", "")
    filename_ids, filename_names = set(), set()
    for key, entry in entries.items():
        email = entry.get("email", "")
        identifiers = [email]
        if "@" in email:
            identifiers.append(email.split("@", 1)[0])
        # Legacy rosters can key a student by name. A single given name is
        # still insufficient evidence, even when it happens to be the key.
        if normalize(key) != normalize(entry.get("name")) or len(normalize(key).split()) >= 2:
            identifiers.append(key)
        variants = name_variants(entry)
        if any(contains(t, v) for t in (text, local) for v in identifiers):
            filename_ids.add(key)
        if any(contains(t, v) for t in (text, local) for v in variants):
            filename_names.add(key)

    filenames = filename_ids | filename_names
    if len(filename_ids) == 1:
        key = next(iter(filename_ids))
        # An explicit ID disambiguates classmates with identical full names.
        # Several DIFFERENT names in a file remain a conflict to review.
        if not filename_names or (key in filename_names and all(
                normalize(entries[k].get("name")) == normalize(entries[key].get("name"))
                for k in filename_names)):
            filenames = {key}

    metadata = set()
    people = (file.get("owners") or []) + [file.get("sharingUser"),
                                         file.get("lastModifyingUser")]
    people += file.get("permissions") or []
    for person in people:
        email = str((person or {}).get("emailAddress") or "").strip().casefold()
        if not email or "@" not in email:
            continue
        metadata.update(key for key, e in entries.items()
                        if str(e.get("email") or "").strip().casefold() == email)

    candidates = filenames | metadata
    if len(candidates) != 1:
        return None, "ambiguous" if candidates else "unmatched"
    key = next(iter(candidates))
    return entries[key], "filename" if key in filenames else "metadata"
