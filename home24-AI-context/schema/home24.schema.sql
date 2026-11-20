-- schema live home24.db (без данных)

CREATE TABLE contacts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              phone TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL DEFAULT '',
              username TEXT NOT NULL DEFAULT '',
              status TEXT NOT NULL DEFAULT 'pending',
              chat_id TEXT NOT NULL DEFAULT '',
              last_error TEXT NOT NULL DEFAULT '',
              manager_id TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            , telegram_user_id TEXT NOT NULL DEFAULT '', tg_status TEXT NOT NULL DEFAULT '', tg_account_id TEXT NOT NULL DEFAULT '', send_on TEXT NOT NULL DEFAULT '');

CREATE TABLE global_stops (
              key TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              created_at REAL NOT NULL
            );

CREATE TABLE inbound_queue (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id TEXT NOT NULL,
              text TEXT NOT NULL,
              message_id TEXT NOT NULL DEFAULT '',
              manager_id TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL,
              UNIQUE(chat_id, message_id, manager_id)
            );

CREATE TABLE messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id TEXT NOT NULL,
              role TEXT NOT NULL,
              text TEXT NOT NULL,
              sender_label TEXT NOT NULL DEFAULT '',
              created_at REAL NOT NULL
            );

CREATE TABLE meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

CREATE TABLE sessions (
              chat_id TEXT PRIMARY KEY,
              name TEXT NOT NULL DEFAULT '',
              step TEXT NOT NULL DEFAULT 'greeting',
              dates TEXT NOT NULL DEFAULT '',
              guests TEXT NOT NULL DEFAULT '',
              district TEXT NOT NULL DEFAULT '',
              returning_guest TEXT NOT NULL DEFAULT '',
              favorite TEXT NOT NULL DEFAULT '',
              handed_off INTEGER NOT NULL DEFAULT 0,
              manager_id TEXT NOT NULL DEFAULT '',
              context_json TEXT NOT NULL DEFAULT '{}',
              updated_at REAL NOT NULL
            , archived INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '');

CREATE TABLE sqlite_sequence(name,seq);
