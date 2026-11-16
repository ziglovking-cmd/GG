export type TournamentStatus =
  | "draft"
  | "open"
  | "locked"
  | "checkin"
  | "live"
  | "finished"
  | "cancelled";

export type PaymentStatus = "pending" | "paid" | "refunded";
export type ReadyStatus = "waiting" | "ready" | "noshow" | "forfeit" | "bot";

export type Tournament = {
  id: number;
  title: string;
  game: string;
  entry_fee_rub: number;
  prize_rub: number;
  status: TournamentStatus;
  stream_url: string | null;
  stream_embed_url: string | null;
  max_players: number;
  starts_at: string | null;
  rules: string | null;
  bracket_json: string | null;
  room_code: string | null;
  checkin_seconds: number;
  lobby_opened_at: string | null;
  lobby_deadline_at: string | null;
  winner_registration_id: number | null;
  created_by_player_id: number | null;
  channel_message_id: number | null;
  created_at: string;
  updated_at: string;
  paid_count?: number;
  pending_count?: number;
  total_count?: number;
  ready_count?: number;
  noshow_count?: number;
};

export type Registration = {
  id: number;
  tournament_id: number;
  player_id: number;
  brawl_tag: string;
  payment_status: PaymentStatus;
  ready_status: ReadyStatus;
  ready_at: string | null;
  seed: number | null;
  note: string | null;
  created_at: string;
  display_name?: string;
  username?: string | null;
  telegram_id?: number | null;
};

export type Player = {
  id: number;
  telegram_id: number | null;
  username: string | null;
  display_name: string;
  brawl_tag: string;
  balance_rub: number;
  session_token: string | null;
  created_at: string;
};

export type SlotStatus = "active" | "noshow" | "bot" | "eliminated" | "bye";

export type BracketMatch = {
  id: string;
  round: number;
  slot: number;
  playerAId: number | null;
  playerBId: number | null;
  playerAName: string | null;
  playerBName: string | null;
  playerATag: string | null;
  playerBTag: string | null;
  playerAStatus: SlotStatus;
  playerBStatus: SlotStatus;
  winnerId: number | null;
  score: string | null;
};

export type Bracket = {
  size: number;
  rounds: number;
  matches: BracketMatch[];
  noshowPlayerIds: number[];
};

export type Deposit = {
  id: number;
  player_id: number;
  amount_rub: number;
  status: "pending" | "confirmed" | "rejected";
  method: string;
  external_id: string | null;
  created_at: string;
  confirmed_at: string | null;
};

export type FriendQueueItem = {
  id: number;
  player_id: number;
  brawl_tag: string;
  status: "pending" | "added" | "failed";
  note: string | null;
  created_at: string;
  updated_at: string;
  display_name?: string;
};
