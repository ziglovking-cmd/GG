create table if not exists settings (
  key text primary key,
  value text not null
);

create table if not exists tournaments (
  id serial primary key,
  title text not null,
  game text not null default 'Brawl Stars',
  entry_fee_rub integer not null default 50,
  prize_rub integer not null default 150,
  status text not null default 'open'
    check (status in ('draft', 'open', 'locked', 'checkin', 'live', 'finished', 'cancelled')),
  stream_url text,
  stream_embed_url text,
  max_players integer not null default 8,
  starts_at timestamptz,
  rules text,
  bracket_json text,
  room_code text,
  checkin_seconds integer not null default 60,
  lobby_opened_at timestamptz,
  lobby_deadline_at timestamptz,
  winner_registration_id integer,
  created_by_player_id integer,
  channel_message_id bigint,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists players (
  id serial primary key,
  telegram_id bigint unique,
  username text,
  display_name text not null,
  brawl_tag text not null,
  balance_rub integer not null default 0,
  session_token text unique,
  created_at timestamptz not null default now()
);

create table if not exists registrations (
  id serial primary key,
  tournament_id integer not null references tournaments(id),
  player_id integer not null references players(id),
  brawl_tag text not null,
  payment_status text not null default 'pending'
    check (payment_status in ('pending', 'paid', 'refunded')),
  ready_status text not null default 'waiting'
    check (ready_status in ('waiting', 'ready', 'noshow', 'forfeit', 'bot')),
  ready_at timestamptz,
  seed integer,
  note text,
  created_at timestamptz not null default now(),
  unique (tournament_id, player_id)
);

create table if not exists deposits (
  id serial primary key,
  player_id integer not null references players(id),
  amount_rub integer not null check (amount_rub > 0),
  status text not null default 'pending'
    check (status in ('pending', 'confirmed', 'rejected')),
  method text not null default 'manual',
  external_id text,
  created_at timestamptz not null default now(),
  confirmed_at timestamptz
);

create table if not exists friend_queue (
  id serial primary key,
  player_id integer not null references players(id),
  brawl_tag text not null,
  status text not null default 'pending'
    check (status in ('pending', 'added', 'failed')),
  note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (player_id, brawl_tag)
);

create table if not exists channel_posts (
  id serial primary key,
  kind text not null,
  tournament_id integer references tournaments(id),
  body text not null,
  telegram_message_id bigint,
  created_at timestamptz not null default now()
);

create index if not exists registrations_tournament_idx on registrations(tournament_id);
create index if not exists tournaments_status_idx on tournaments(status);
create index if not exists deposits_player_idx on deposits(player_id);
create index if not exists friend_queue_status_idx on friend_queue(status);
create index if not exists players_brawl_tag_idx on players(brawl_tag);
create index if not exists registrations_ready_idx on registrations(tournament_id, ready_status);
