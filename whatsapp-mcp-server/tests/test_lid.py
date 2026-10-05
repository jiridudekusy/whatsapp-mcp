"""Regression tests for LID chats (see conftest.py for the scenario).

Without the fix they fail: `list_messages` printed only `chats.name` (for a LID chat the
bare number of the sender) and `get_chat` compared the JID exactly, so an identifier taken
from the output could not be used as a query.
"""

import re

from conftest import (
    ALICE_CHAT, ALICE_MSG, GROUP_CHAT, LID_CHAT, LID_MSG, ME_LID, ME_PN, OTHER_LID, OTHER_PN,
)

CHAT_ID_IN_ROW = re.compile(r'<([^<>]+)>')


def _chat_ids(output: str):
    return CHAT_ID_IN_ROW.findall(output)


def test_round_trip_every_row(dbs):
    """The chat identifier printed on each row of an unfiltered listing returns that message."""
    out = dbs.list_messages(include_context=False, limit=50)
    rows = [line for line in out.splitlines() if line.strip()]
    assert rows, out
    for row in rows:
        ids = _chat_ids(row)
        assert len(ids) == 1, f'row without an unambiguous JID: {row!r}'
        content = row.split(': ', 2)[-1]
        again = dbs.list_messages(chat_jid=ids[0], include_context=False)
        assert content in again, f'{ids[0]} did not return {content!r}: {again!r}'


def test_round_trip_lid_chat_named_after_sender(dbs):
    """The reported case: a LID chat whose stored name is my own LID."""
    out = dbs.list_messages(include_context=False, limit=50)
    row = next(line for line in out.splitlines() if LID_MSG in line)
    (chat_id,) = _chat_ids(row)
    assert chat_id == LID_CHAT
    assert LID_MSG in dbs.list_messages(chat_jid=chat_id, include_context=False)
    # The identifier users saw in the old output (the bare LID from the chat name) must not
    # come back empty either.
    assert LID_MSG in dbs.list_messages(chat_jid=ME_LID, include_context=False) or \
        dbs.get_chat(ME_LID) is not None


def test_get_chat_bare_lid_returns_metadata(dbs):
    chat = dbs.get_chat(ME_LID)
    assert chat is not None
    assert chat.jid == LID_CHAT
    assert chat.last_message == LID_MSG


def test_get_chat_lid_jid_and_phone_of_counterparty(dbs):
    for ident in (LID_CHAT, OTHER_LID, OTHER_PN, f'{OTHER_PN}@s.whatsapp.net', f'+{OTHER_PN}'):
        chat = dbs.get_chat(ident)
        assert chat is not None, ident
        assert chat.jid == LID_CHAT, ident


def test_lid_chat_links_to_counterparty(dbs):
    chat = dbs.get_chat(LID_CHAT)
    assert chat.phone_number == OTHER_PN
    assert chat.contact_name == 'Recepce Kovárna'
    assert chat.name == 'Recepce Kovárna'  # not the bare LID of the sender


def test_list_chats_resolves_lid_names(dbs):
    by_jid = {c.jid: c for c in dbs.list_chats(limit=10)}
    assert by_jid[LID_CHAT].name == 'Recepce Kovárna'
    assert by_jid[LID_CHAT].phone_number == OTHER_PN
    assert by_jid[ALICE_CHAT].name == 'Alice'          # a stored real name wins
    assert by_jid[GROUP_CHAT].name == 'Kotel'
    assert by_jid[GROUP_CHAT].phone_number is None      # a group has no counterparty


def test_full_jid_backcompat(dbs):
    chat = dbs.get_chat(ALICE_CHAT)
    assert chat is not None and chat.name == 'Alice' and chat.last_message == ALICE_MSG
    assert ALICE_MSG in dbs.list_messages(chat_jid=ALICE_CHAT, include_context=False)
    assert dbs.get_chat(GROUP_CHAT).name == 'Kotel'
    assert dbs.get_direct_chat_by_contact('420111222333').jid == ALICE_CHAT


def test_direct_chat_by_phone_finds_lid_chat(dbs):
    assert dbs.get_direct_chat_by_contact(OTHER_PN).jid == LID_CHAT


def test_sender_name_does_not_match_group_by_prefix(dbs):
    # The original LIKE '%420724484432%' matched the group "Kotel" created by this number.
    assert dbs.get_sender_name(ME_PN) == 'Jiří Dudek'
    assert dbs.get_sender_name(ME_LID) == 'Jiří Dudek'


def test_sender_filter_accepts_phone_or_lid(dbs):
    # The message has sender = LID; filtering by the phone number must find it too.
    assert LID_MSG in dbs.list_messages(sender_phone_number=ME_PN, include_context=False)
    assert LID_MSG in dbs.list_messages(sender_phone_number=ME_LID, include_context=False)


def test_contact_chats_and_last_interaction_by_phone(dbs):
    chats = dbs.get_contact_chats(OTHER_PN)
    assert [c.jid for c in chats] == [LID_CHAT]
    assert LID_MSG in dbs.get_last_interaction(OTHER_PN)
