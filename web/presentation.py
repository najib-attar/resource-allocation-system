"""Display-only formatting; persisted identities and names remain unchanged."""

import re


def person_name(value):
    if not isinstance(value, str):
        return value
    # Only the known fictional generator's suffix is decorative, not a real name.
    return re.sub(r"^(Demo (?:Mira|Elio|Nora|Tessa) (?:Vale|Birch|Ashford|Reed)) [0-9]{4,}$", r"\1", value)
