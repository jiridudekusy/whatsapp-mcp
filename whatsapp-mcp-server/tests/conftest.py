"""Fixtures: a miniature messages.db + whatsapp.db reproducing the LID problem.

The scenario mirrors a real case from 2026-09-19:
- me: phone 420724484432, LID 212777058713738, contact "Jiří Dudek"
- counterparty: phone 420775931113, LID 159472202842303, push name "Recepce Kovárna"
- the chat with the counterparty is stored as `159472202842303@lid` and the Go bridge
  named it `212777058713738` (the bare LID of the sender) - exactly what broke the
  round trip from list_messages output back to a query.
- a regular chat `420111222333@s.whatsapp.net` "Alice" - backwards compatibility
- a group `420724484432-1632738465@g.us` "Kotel" created by my number - a trap for
  substring matching
"""

import os
import sqlite3
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
# Server sources: the parent directory by default, overridable for out-of-tree runs.
SERVER_DIR = os.environ.get('WHATSAPP_MCP_SERVER_DIR', os.path.dirname(HERE))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

ME_PN, ME_LID = '420724484432', '212777058713738'
OTHER_PN, OTHER_LID = '420775931113', '159472202842303'
LID_CHAT = f'{OTHER_LID}@lid'
ALICE_CHAT = '420111222333@s.whatsapp.net'
GROUP_CHAT = f'{ME_PN}-1632738465@g.us'
LID_MSG = 'Dobrý den, prosím prodlužte nám rezervaci do 12:00.'
ALICE_MSG = 'Ahoj, zítra v 8?'


@pytest.fixture
def dbs(tmp_path, monkeypatch):
    store = tmp_path / 'store'
    store.mkdir()
    messages_db = store / 'messages.db'
    whatsapp_db = store / 'whatsapp.db'

    m = sqlite3.connect(messages_db)
    m.executescript(
        """
        CREATE TABLE chats (jid TEXT PRIMARY KEY, name TEXT, last_message_time TIMESTAMP);
        CREATE TABLE messages (
            id TEXT, chat_jid TEXT, sender TEXT, content TEXT, timestamp TIMESTAMP,
            is_from_me BOOLEAN, media_type TEXT, filename TEXT, url TEXT, media_key BLOB,
            file_sha256 BLOB, file_enc_sha256 BLOB, file_length INTEGER,
            PRIMARY KEY (id, chat_jid), FOREIGN KEY (chat_jid) REFERENCES chats(jid)
        );
        """
    )
    m.executemany(
        'INSERT INTO chats VALUES (?,?,?)',
        [
            (LID_CHAT, ME_LID, '2026-09-20 07:19:34+00:00'),
            (ALICE_CHAT, 'Alice', '2026-09-18 10:00:00+00:00'),
            (GROUP_CHAT, 'Kotel', '2024-05-21 14:12:08+00:00'),
        ],
    )
    m.executemany(
        'INSERT INTO messages (id, chat_jid, sender, content, timestamp, is_from_me) VALUES (?,?,?,?,?,?)',
        [
            ('M1', LID_CHAT, ME_LID, LID_MSG, '2026-09-20 07:19:34+00:00', 1),
            ('M2', ALICE_CHAT, '420111222333', ALICE_MSG, '2026-09-18 10:00:00+00:00', 0),
            ('M3', GROUP_CHAT, ME_PN, 'Pivo?', '2024-05-21 14:12:08+00:00', 1),
        ],
    )
    m.commit()
    m.close()

    w = sqlite3.connect(whatsapp_db)
    w.executescript(
        """
        CREATE TABLE whatsmeow_lid_map (lid TEXT PRIMARY KEY, pn TEXT UNIQUE NOT NULL);
        CREATE TABLE whatsmeow_contacts (
            our_jid TEXT, their_jid TEXT, first_name TEXT, full_name TEXT, push_name TEXT,
            business_name TEXT, redacted_phone TEXT, PRIMARY KEY (our_jid, their_jid)
        );
        """
    )
    w.executemany('INSERT INTO whatsmeow_lid_map VALUES (?,?)', [(ME_LID, ME_PN), (OTHER_LID, OTHER_PN)])
    w.executemany(
        'INSERT INTO whatsmeow_contacts (our_jid, their_jid, first_name, full_name, push_name) VALUES (?,?,?,?,?)',
        [
            ('me', f'{ME_PN}@s.whatsapp.net', '', 'Jiří Dudek', 'Jiří Dudek'),
            ('me', f'{ME_LID}@lid', None, None, 'Jiří Dudek'),
            ('me', f'{OTHER_LID}@lid', None, None, 'Recepce Kovárna'),
            ('me', ALICE_CHAT, 'Alice', 'Alice Nováková', 'Alice'),
        ],
    )
    w.commit()
    w.close()

    import jids
    import whatsapp

    monkeypatch.setattr(whatsapp, 'MESSAGES_DB_PATH', str(messages_db))
    monkeypatch.setattr(jids, 'WHATSAPP_DB_PATH', str(whatsapp_db))
    return whatsapp
