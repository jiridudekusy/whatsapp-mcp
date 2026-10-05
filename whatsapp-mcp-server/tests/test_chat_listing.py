"""Regression tests for chat listings.

- list_chats(include_last_message=False) selected messages.* without joining messages,
  raised "no such column" and returned an empty list.
- get_contact_chats joined every message of the contact and returned one row per message
  instead of one per chat.
"""

import sqlite3

from conftest import ALICE_CHAT, GROUP_CHAT, LID_CHAT, LID_MSG, OTHER_LID, OTHER_PN


def _add_messages(whatsapp, chat, sender, n):
    conn = sqlite3.connect(whatsapp.MESSAGES_DB_PATH)
    for i in range(n):
        conn.execute(
            'INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me) VALUES (?,?,?,?,?,?)',
            (f'X{chat[:3]}{i}', chat, sender, f'msg {i}', f'2026-09-0{i + 1} 10:00:00+00:00', 0),
        )
    conn.commit()
    conn.close()


def test_list_chats_without_last_message_returns_chats(dbs):
    chats = dbs.list_chats(limit=10, include_last_message=False)
    assert {c.jid for c in chats} == {LID_CHAT, ALICE_CHAT, GROUP_CHAT}
    assert all(c.last_message is None and c.last_sender is None for c in chats)
    # names and the counterparty are still resolved
    assert {c.jid: c.name for c in chats}[LID_CHAT] == 'Recepce Kovárna'
    # and the default still carries the last message
    assert {c.jid: c.last_message for c in dbs.list_chats(limit=10)}[LID_CHAT] == LID_MSG


def test_contact_chats_one_row_per_chat(dbs):
    _add_messages(dbs, LID_CHAT, OTHER_LID, 5)            # 6 messages in the direct chat
    _add_messages(dbs, GROUP_CHAT, OTHER_PN, 3)           # the contact also wrote in a group
    chats = dbs.get_contact_chats(OTHER_PN, limit=20)
    assert [c.jid for c in chats] == [LID_CHAT, GROUP_CHAT]
    assert chats[0].last_message == LID_MSG             # newest message of the direct chat


def test_contact_chats_pagination_counts_chats_not_messages(dbs):
    _add_messages(dbs, LID_CHAT, OTHER_LID, 5)
    assert len(dbs.get_contact_chats(OTHER_PN, limit=1)) == 1
    assert dbs.get_contact_chats(OTHER_PN, limit=1, page=1) == []
