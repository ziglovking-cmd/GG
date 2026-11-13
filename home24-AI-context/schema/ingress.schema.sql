-- schema ingress.sqlite (без данных)

CREATE TABLE events (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ts REAL NOT NULL,
                  ip TEXT NOT NULL DEFAULT '',
                  ua TEXT NOT NULL DEFAULT '',
                  username TEXT NOT NULL DEFAULT '',
                  kind TEXT NOT NULL DEFAULT '',
                  path TEXT NOT NULL DEFAULT '',
                  status INTEGER NOT NULL DEFAULT 0,
                  detail TEXT NOT NULL DEFAULT ''
                );

CREATE TABLE sqlite_sequence(name,seq);
