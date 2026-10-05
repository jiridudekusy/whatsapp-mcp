"""Resolve WhatsApp identities: LID <-> phone number <-> JID.

Since 2025 WhatsApp addresses some users by a "LID" (`<number>@lid`) instead of their
phone number (`<number>@s.whatsapp.net`). The same person can therefore appear in
`messages.db` under both forms, and as a bare number in the `sender` column. whatsmeow
keeps the LID -> phone mapping and the contact names in `store/whatsapp.db`
(`whatsmeow_lid_map`, `whatsmeow_contacts`); this module derives every equivalent form
of an identifier from them so that a query in any form finds the same chat.

All functions tolerate a missing `whatsapp.db` (they then return only the syntactic
variants).
"""

import os.path
import re
import sqlite3
from typing import List, Optional

WHATSAPP_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'whatsapp-bridge', 'store', 'whatsapp.db'
)

PN_SERVER = 's.whatsapp.net'
LID_SERVER = 'lid'
GROUP_SERVER = 'g.us'

_NUMERIC = re.compile(r'^\d+$')


def split_jid(identifier: str):
    """Return (user, server). Without '@' the server is None. Strips '+', spaces, dashes."""
    identifier = (identifier or '').strip()
    if '@' in identifier:
        user, server = identifier.split('@', 1)
    else:
        user, server = identifier, None
    if server != GROUP_SERVER:
        user = re.sub(r'[\s+\-()]', '', user)
    return user, server


def is_group(identifier: str) -> bool:
    return (identifier or '').endswith('@' + GROUP_SERVER)


def looks_like_bare_id(value: Optional[str]) -> bool:
    """A number without a name - a LID or phone, as the bridge stores it in `chats.name`."""
    return bool(value) and bool(_NUMERIC.match(value.strip()))


def _query(sql: str, params: tuple):
    if not os.path.exists(WHATSAPP_DB_PATH):
        return []
    try:
        conn = sqlite3.connect(f'file:{WHATSAPP_DB_PATH}?mode=ro', uri=True)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def lid_to_pn(lid: str) -> Optional[str]:
    rows = _query('SELECT pn FROM whatsmeow_lid_map WHERE lid = ?', (lid,))
    return rows[0][0] if rows else None


def pn_to_lid(pn: str) -> Optional[str]:
    rows = _query('SELECT lid FROM whatsmeow_lid_map WHERE pn = ?', (pn,))
    return rows[0][0] if rows else None


def user_variants(identifier: str) -> List[str]:
    """Bare identifiers of the same person: [phone, LID] in any order, without duplicates.

    The `messages.sender` column holds a bare number - either a phone number or a LID.
    """
    user, server = split_jid(identifier)
    if not user or server == GROUP_SERVER:
        return [user] if user else []
    out = [user]
    if server == LID_SERVER:
        pn = lid_to_pn(user)
        if pn:
            out.append(pn)
    elif server == PN_SERVER:
        lid = pn_to_lid(user)
        if lid:
            out.append(lid)
    else:
        for other in (lid_to_pn(user), pn_to_lid(user)):
            if other:
                out.append(other)
    return _dedupe(out)


def candidate_jids(identifier: str) -> List[str]:
    """All JIDs a chat with the given identifier may be stored under.

    Accepts a full JID (`x@s.whatsapp.net`, `x@lid`, `x@g.us`) or a bare number (phone or
    LID). A full JID comes first so that an exact match takes precedence.
    """
    identifier = (identifier or '').strip()
    if not identifier:
        return []
    user, server = split_jid(identifier)
    if server == GROUP_SERVER or (server and server not in (PN_SERVER, LID_SERVER)):
        return [identifier]
    out = [identifier] if server else []
    for u in user_variants(identifier):
        out.append(f'{u}@{PN_SERVER}')
        out.append(f'{u}@{LID_SERVER}')
    return _dedupe(out)


def phone_number(identifier: str) -> Optional[str]:
    """The person's phone number when known (directly or through the LID map)."""
    user, server = split_jid(identifier)
    if not user or server == GROUP_SERVER:
        return None
    if server == PN_SERVER:
        return user
    if server == LID_SERVER:
        return lid_to_pn(user)
    pn = lid_to_pn(user)
    if pn:
        return pn
    # A bare number that is not a known LID: treat it as a phone number unless whatsmeow
    # knows it as a LID.
    return user if pn_to_lid(user) or not _query(
        'SELECT 1 FROM whatsmeow_lid_map WHERE lid = ?', (user,)
    ) else None


def contact_name(identifier: str) -> Optional[str]:
    """Contact name from whatsmeow_contacts (full_name > push_name > business_name > first_name)."""
    cands = [c for c in candidate_jids(identifier) if not is_group(c)]
    if not cands:
        return None
    placeholders = ','.join('?' * len(cands))
    rows = _query(
        f'SELECT full_name, push_name, business_name, first_name FROM whatsmeow_contacts '
        f'WHERE their_jid IN ({placeholders})',
        tuple(cands),
    )
    for column in range(4):
        for row in rows:
            if row[column]:
                return row[column]
    return None


def display_name(identifier: str, stored_name: Optional[str]) -> Optional[str]:
    """Name to show: the stored name when it is a real name; else the contact; else the phone."""
    if stored_name and not looks_like_bare_id(stored_name):
        return stored_name
    if is_group(identifier):
        return stored_name
    return contact_name(identifier) or phone_number(identifier) or stored_name


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
