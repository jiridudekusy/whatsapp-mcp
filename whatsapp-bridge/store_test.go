package main

// Regression tests for the message store: reactions and the rule that last_message_time
// only ever points at a stored message.

import (
	"database/sql"
	"os"
	"testing"
	"time"
)

func newTestStore(t *testing.T) *MessageStore {
	t.Helper()
	dir := t.TempDir()
	if err := os.MkdirAll(dir+"/store", 0o755); err != nil {
		t.Fatal(err)
	}
	wd, _ := os.Getwd()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(wd) })
	store, err := NewMessageStore() // opens store/messages.db relative to the working directory
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { store.Close() })
	return store
}

func mustExec(t *testing.T, store *MessageStore, q string, args ...interface{}) {
	t.Helper()
	if _, err := store.db.Exec(q, args...); err != nil {
		t.Fatalf("%s: %v", q, err)
	}
}

var (
	msgTime      = time.Date(2026, 9, 20, 7, 19, 34, 0, time.UTC)
	reactionTime = time.Date(2026, 9, 20, 7, 25, 31, 0, time.UTC)
	lidChat      = "159472202842303@lid"
)

func seedLidChat(t *testing.T, store *MessageStore) {
	t.Helper()
	if err := store.StoreChat(lidChat, "212777058713738", msgTime); err != nil {
		t.Fatal(err)
	}
	if err := store.StoreMessage("M1", lidChat, "212777058713738", "Hello, please extend our booking.", msgTime, true,
		"", "", "", nil, nil, nil, 0); err != nil {
		t.Fatal(err)
	}
}

func reactions(t *testing.T, store *MessageStore) []string {
	t.Helper()
	rows, err := store.db.Query("SELECT message_id || '|' || chat_jid || '|' || sender || '|' || emoji FROM reactions ORDER BY sender")
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var s string
		rows.Scan(&s)
		out = append(out, s)
	}
	return out
}

func TestStoreReactionAddChangeRemove(t *testing.T) {
	store := newTestStore(t)
	seedLidChat(t, store)

	if err := store.StoreReaction("M1", lidChat, "159472202842303", "👍", reactionTime); err != nil {
		t.Fatal(err)
	}
	if got := reactions(t, store); len(got) != 1 || got[0] != "M1|"+lidChat+"|159472202842303|👍" {
		t.Fatalf("after add: %v", got)
	}
	// a changed reaction overwrites the previous one
	if err := store.StoreReaction("M1", lidChat, "159472202842303", "❤️", reactionTime.Add(time.Minute)); err != nil {
		t.Fatal(err)
	}
	if got := reactions(t, store); len(got) != 1 || got[0] != "M1|"+lidChat+"|159472202842303|❤️" {
		t.Fatalf("after change: %v", got)
	}
	// an empty text removes it
	if err := store.StoreReaction("M1", lidChat, "159472202842303", "", reactionTime.Add(2*time.Minute)); err != nil {
		t.Fatal(err)
	}
	if got := reactions(t, store); len(got) != 0 {
		t.Fatalf("after removal: %v", got)
	}
}

func TestStoreReactionResolvesChatByMessageID(t *testing.T) {
	// The reaction arrives under the phone-number form of the JID while the message is
	// stored under the LID form - they must meet.
	store := newTestStore(t)
	seedLidChat(t, store)
	if err := store.StoreReaction("M1", "420775931113@s.whatsapp.net", "420775931113", "👍", reactionTime); err != nil {
		t.Fatal(err)
	}
	got := reactions(t, store)
	if len(got) != 1 || got[0] != "M1|"+lidChat+"|420775931113|👍" {
		t.Fatalf("reaction not matched to the message's chat: %v", got)
	}
}

func TestReactionDoesNotBecomeMessageAndDoesNotMoveChatTime(t *testing.T) {
	store := newTestStore(t)
	seedLidChat(t, store)
	if err := store.StoreReaction("M1", lidChat, "159472202842303", "👍", reactionTime); err != nil {
		t.Fatal(err)
	}
	var n int
	store.db.QueryRow("SELECT COUNT(*) FROM messages WHERE chat_jid = ?", lidChat).Scan(&n)
	if n != 1 {
		t.Fatalf("message count changed: %d", n)
	}
	var last time.Time
	store.db.QueryRow("SELECT last_message_time FROM chats WHERE jid = ?", lidChat).Scan(&last)
	if !last.Equal(msgTime) {
		t.Fatalf("last_message_time moved: %v", last)
	}
}

func TestRepairChatTimesFixesPhantomAndNullsEmptyChats(t *testing.T) {
	store := newTestStore(t)
	seedLidChat(t, store)
	// State left by an unfixed bridge: the chat time points at a reaction (no message there).
	mustExec(t, store, "UPDATE chats SET last_message_time = ? WHERE jid = ?", reactionTime, lidChat)
	// A chat where history sync recorded the time of a message other than the newest.
	if err := store.StoreChat("420111222333@s.whatsapp.net", "Alice", msgTime.Add(-time.Hour)); err != nil {
		t.Fatal(err)
	}
	store.StoreMessage("A1", "420111222333@s.whatsapp.net", "420111222333", "a", msgTime.Add(-time.Hour), false, "", "", "", nil, nil, nil, 0)
	store.StoreMessage("A2", "420111222333@s.whatsapp.net", "420111222333", "b", msgTime.Add(-30*time.Minute), false, "", "", "", nil, nil, nil, 0)
	// A chat without any stored message (its last event was an unsupported type).
	if err := store.StoreChat("420999888777@s.whatsapp.net", "Nobody", msgTime); err != nil {
		t.Fatal(err)
	}
	// A consistent chat - must stay untouched.
	if err := store.StoreChat("420555666777@s.whatsapp.net", "Ok", msgTime); err != nil {
		t.Fatal(err)
	}
	store.StoreMessage("O1", "420555666777@s.whatsapp.net", "420555666777", "ok", msgTime, false, "", "", "", nil, nil, nil, 0)

	n, err := store.RepairChatTimes()
	if err != nil {
		t.Fatal(err)
	}
	if n != 3 {
		t.Fatalf("repaired %d chats, want 3", n)
	}
	check := func(jid string, want *time.Time) {
		t.Helper()
		var got sql.NullTime
		if err := store.db.QueryRow("SELECT last_message_time FROM chats WHERE jid = ?", jid).Scan(&got); err != nil {
			t.Fatal(err)
		}
		if want == nil {
			if got.Valid {
				t.Fatalf("%s: want NULL, got %v", jid, got.Time)
			}
			return
		}
		if !got.Valid || !got.Time.Equal(*want) {
			t.Fatalf("%s: want %v, got %v (valid=%v)", jid, *want, got.Time, got.Valid)
		}
	}
	check(lidChat, &msgTime)
	newest := msgTime.Add(-30 * time.Minute)
	check("420111222333@s.whatsapp.net", &newest)
	check("420999888777@s.whatsapp.net", nil)
	check("420555666777@s.whatsapp.net", &msgTime)

	// Idempotent: a second pass changes nothing.
	if n, _ := store.RepairChatTimes(); n != 0 {
		t.Fatalf("second pass repaired %d", n)
	}
	// After the repair no chat points at a time without a message.
	var phantom int
	store.db.QueryRow(`SELECT COUNT(*) FROM chats c WHERE last_message_time IS NOT NULL AND NOT EXISTS
		(SELECT 1 FROM messages m WHERE m.chat_jid = c.jid AND m.timestamp = c.last_message_time)`).Scan(&phantom)
	if phantom != 0 {
		t.Fatalf("%d phantom times left", phantom)
	}
}

func TestStoreMessageDoesNotDuplicateAcrossJidVariants(t *testing.T) {
	// A message stored live under the LID chat arrives again from an on-demand history
	// sync under the phone-number JID.
	store := newTestStore(t)
	seedLidChat(t, store)
	if err := store.StoreChat("420775931113@s.whatsapp.net", "Reception", msgTime); err != nil {
		t.Fatal(err)
	}
	if err := store.StoreMessage("M1", "420775931113@s.whatsapp.net", "420724484432", "Hello, please extend our booking.", msgTime, true,
		"", "", "", nil, nil, nil, 0); err != nil {
		t.Fatal(err)
	}
	var n int
	store.db.QueryRow("SELECT COUNT(*) FROM messages WHERE id = 'M1'").Scan(&n)
	if n != 1 {
		t.Fatalf("message M1 stored %d times", n)
	}
	var chat string
	store.db.QueryRow("SELECT chat_jid FROM messages WHERE id = 'M1'").Scan(&chat)
	if chat != lidChat {
		t.Fatalf("message moved under %s", chat)
	}
	// Re-storing the same message under the SAME chat (history sync upsert) stays allowed.
	if err := store.StoreMessage("M1", lidChat, "212777058713738", "Hello (edited)", msgTime, true, "", "", "", nil, nil, nil, 0); err != nil {
		t.Fatal(err)
	}
	var content string
	store.db.QueryRow("SELECT content FROM messages WHERE id = 'M1'").Scan(&content)
	if content != "Hello (edited)" {
		t.Fatalf("upsert under the same chat did not happen: %q", content)
	}
}
