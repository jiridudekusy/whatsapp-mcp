"""Regression tests for reactions (builds on test_lid.py; scenario in conftest.py).

Without the fix they fail: the bridge dropped reactions (no `reactions` table) and moved
the chat's `last_message_time` to the reaction's time, which `get_chat(include_last_message=True)`
then could not resolve to any message.
"""

import sqlite3

from conftest import LID_CHAT, LID_MSG, OTHER_LID, OTHER_PN, ALICE_CHAT

REACTION_TS = '2026-09-20 07:25:31+00:00'
MESSAGE_TS = '2026-09-20 07:19:34+00:00'


def _add_reaction(whatsapp, emoji='👍', sender=OTHER_LID, ts=REACTION_TS, phantom_time=False):
    conn = sqlite3.connect(whatsapp.MESSAGES_DB_PATH)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS reactions (message_id TEXT, chat_jid TEXT, sender TEXT, emoji TEXT, '
        'timestamp TIMESTAMP, PRIMARY KEY (message_id, chat_jid, sender))'
    )
    conn.execute('INSERT OR REPLACE INTO reactions VALUES (?,?,?,?,?)', ('M1', LID_CHAT, sender, emoji, ts))
    if phantom_time:
        # The state an unfixed bridge left behind: the chat time points at the reaction.
        conn.execute('UPDATE chats SET last_message_time = ? WHERE jid = ?', (ts, LID_CHAT))
    conn.commit()
    conn.close()


def test_reaction_visible_on_message_with_emoji_and_sender(dbs):
    _add_reaction(dbs)
    out = dbs.list_messages(chat_jid=LID_CHAT, include_context=False)
    row = next(l for l in out.splitlines() if LID_MSG in l)
    assert '👍' in row
    assert 'Recepce Kovárna' in row          # who reacted (LID -> contact)
    assert '2026-09-20 07:25:31' in row


def test_reaction_does_not_change_message_count_or_order(dbs):
    before = dbs.list_messages(include_context=False, limit=50)
    _add_reaction(dbs)
    after = dbs.list_messages(include_context=False, limit=50)
    strip = lambda s: [l.split(' [reactions:')[0] for l in s.splitlines() if l.strip()]
    assert strip(after) == strip(before)
    # a reaction does not behave like a message in time filters either
    assert 'No messages' in dbs.list_messages(after='2026-09-20T07:19:35+00:00', include_context=False)


def test_reaction_in_context_and_last_interaction(dbs):
    _add_reaction(dbs)
    ctx = dbs.get_message_context('M1', before=1, after=1)
    assert ctx.message.reactions and ctx.message.reactions[0]['emoji'] == '👍'
    assert '👍' in dbs.get_last_interaction(OTHER_PN)


def test_changed_and_removed_reaction(dbs):
    _add_reaction(dbs, emoji='👍')
    _add_reaction(dbs, emoji='❤️')            # change: same sender, new emoji
    out = dbs.list_messages(chat_jid=LID_CHAT, include_context=False)
    assert '❤️' in out and '👍' not in out
    conn = sqlite3.connect(dbs.MESSAGES_DB_PATH)
    conn.execute('DELETE FROM reactions WHERE message_id = ? AND sender = ?', ('M1', OTHER_LID))  # removal
    conn.commit(); conn.close()
    assert '[reactions:' not in dbs.list_messages(chat_jid=LID_CHAT, include_context=False)


def test_get_chat_last_message_filled_when_time_points_to_message(dbs):
    _add_reaction(dbs)
    chat = dbs.get_chat(LID_CHAT, include_last_message=True)
    assert chat.last_message == LID_MSG
    assert chat.last_sender is not None and chat.last_is_from_me is not None
    assert f'{chat.last_message_time:%Y-%m-%d %H:%M:%S}' == MESSAGE_TS[:19]


def test_no_phantom_last_message_time(dbs):
    """Every chat with a last_message_time has a message at that time (after the bridge fix)."""
    _add_reaction(dbs)
    conn = sqlite3.connect(dbs.MESSAGES_DB_PATH)
    phantom = conn.execute(
        'SELECT jid FROM chats c WHERE last_message_time IS NOT NULL AND NOT EXISTS '
        '(SELECT 1 FROM messages m WHERE m.chat_jid = c.jid AND m.timestamp = c.last_message_time)'
    ).fetchall()
    conn.close()
    assert phantom == []


def test_phantom_time_from_old_bridge_is_reported_by_get_chat_as_null(dbs):
    """Documents what the Python layer does with an old phantom time: get_chat invents
    nothing; the Go bridge repairs it (RepairChatTimes on start) - see the Go tests."""
    _add_reaction(dbs, phantom_time=True)
    chat = dbs.get_chat(LID_CHAT, include_last_message=True)
    assert chat.last_message is None


def test_old_db_without_reactions_table_still_works(dbs):
    assert LID_MSG in dbs.list_messages(chat_jid=LID_CHAT, include_context=False)
    assert dbs.get_chat(ALICE_CHAT).name == 'Alice'
