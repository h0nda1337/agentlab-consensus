"""User-facing team names, independent of stable server/role identifiers."""
import json
from pathlib import Path

SLOTS = ('Dars', 'Rade', 'Miso')


def display_names(config):
    names = {}
    for slot in SLOTS:
        value = config.get('agents', {}).get(slot, {}).get('display_name', slot)
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 60 or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Cada nombre debe tener de 1 a 60 caracteres y no contener saltos de línea ni controles.')
        names[slot] = value.strip()
    if len({n.casefold() for n in names.values()}) != len(SLOTS):
        raise ValueError('Los tres agentes deben tener nombres distintos.')
    return names


def update_names(config, replacements, path):
    # Validate the whole candidate before changing either the live object or disk.
    candidate = json.loads(json.dumps(config))
    for slot, value in replacements.items():
        candidate['agents'][slot]['display_name'] = value
    names = display_names(candidate)
    target = Path(path)
    temporary = target.with_suffix(target.suffix+'.tmp')
    temporary.write_text(json.dumps(candidate, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(target)
    config.clear()
    config.update(candidate)
    return names
