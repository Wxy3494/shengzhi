export type GameStatus = "playing" | "won" | "lost";
export type SpeakerId = "tian_bo" | "song_zhiyuan" | "gu_tingzhang";

export interface Game {
  id: string;
  schema_version: number;
  revision: number;
  accepted_turns: number;
  status: GameStatus;
  people: number;
  treasury: number;
  grain: number;
  created_at: string;
  updated_at: string;
  realm?: Realm | null;
  ending?: RealmEnding | null;
  opening?: Opening | null;
  conditions?: { resolved: boolean; resolved_turn: number | null; active_until_turn: number; bonus_used: boolean } | null;
  events?: {version: number; config_version?: number; records: RealmEvent[]; pending: RealmEvent[]; forewarnings: {turn: number; text: string}[]; appraisal: EventAppraisal | null; war?: {pending_treaty?: TreatyReport | null}} | null;
  diplomacy?: {records?: DiplomacySession[]; pending?: TreatyReport | null};
}

export interface RealmEvent {
  instance_id: string; event_id: string; name: string; announcement: string; response_hint: string;
  category: string; polarity: string; tier: string; announced_turn: number; respond_by_turn: number | null;
  status: string; outcome: string; immediate_effects: GameState; response_effects?: GameState;
}
export interface EventAppraisal {
  title: string; handling_score: number; event_count: number; resolved_count: number; escalated_count: number;
  repaired_weakness: boolean; legacy_issues: boolean;
}

export interface Opening {
  id: string; name: string; initial: GameState; background: string; advantage: string; difficulty: string; active_until_turn: number;
}
export interface OpeningBrief { game_id: string; briefing: string; source: "model" | "fixture" }

export interface RealmEnding {
  kind: string; title: string; text: string; status: "won" | "lost"; turn_no: number; source_turns: number[];
}
export interface Realm {
  trends?:{id:string;label:string;trend:'easing'|'stable'|'worsening';condition:'quiet'|'building'|'warning'|'critical'}[];
  pressures?: Record<"civil" | "army" | "border" | "bankruptcy", number>;
  warnings: { id: string; threshold?: number; label: string; value: number; level: string; reason: string; advice: string; source_turns: number[] }[];
  reform_started: boolean; reform_steps: number; ending: RealmEnding | null;
}

export interface GameState {
  people: number;
  treasury: number;
  grain: number;
}

export interface Reaction {
  speaker: SpeakerId;
  text: string;
}

export interface PolicyAnalysis {
  benefits?: string[];
  costs?: string[];
  risks?: { condition: string; consequence: string; likelihood: "low" | "medium" | "high"; horizon: "current" | "delayed" }[];
  effect_basis?: string;
}

export interface EchoEffect {
  echo_id: string;
  people: number;
  treasury: number;
  grain: number;
  explanation: string;
  source_policy_id: string;
  source_raw_text?: string;
  created_turn: number;
  reason: string;
}

export interface NewEcho {
  id: string;
  source_policy_id: string;
  created_turn: number;
  delay: number;
  due_turn: number;
  reason: string;
  effect_kind?: "consequence" | "execution";
}

export interface TurnResult {
  events?: {announcement: RealmEvent | null; responses: RealmEvent[]; watch?: string | null; quiet?: string | null; war?: WarReport; treaty?: TreatyReport} | null;
  id: string;
  policy_id: string;
  turn_no: number;
  raw_text: string;
  normalized_goal: string;
  before: GameState;
  applied_effects: GameState;
  after: GameState;
  advisor: string;
  reactions: Reaction[];
  summary: string;
  constraint_notes?: string[];
  policy_analysis?: PolicyAnalysis;
  narration_source?: "model" | "fixture" | "legacy";
  policy_intent?: { category: string; region: string; project: string; action: string; magnitude: string; duration_years: number | null; prohibitions: string[] };
  policy_status?: "active" | "suspended" | "revoked" | "completed";
  execution?: { blocked?: boolean; actual_policy_effect?: GameState };
  echo_effects: EchoEffect[];
  new_echoes: NewEcho[];
}

export interface WarReport {
  version: number; turn: number; outcome: 'victory' | 'defeat'; win_chance: number;
  paid_cost: {treasury: number; grain: number}; returns: {treasury: number; grain: number};
  extra_loss: {treasury: number; grain: number}; effects: GameState;
  ceded_city: boolean; cities_lost: number; collapsed: boolean; text: string;
}

export interface TreatyReport {
  id: string; direction: 'pay' | 'receive'; status: 'pending' | 'accepted' | 'unfunded' | 'expired';
  terms: {cities: number; treasury: number; grain: number; reason: string};
  effects?: GameState; source: 'model' | 'fixture';
}

export interface EchoRecord {
  id: string;
  source_policy_id: string;
  due_turn: number;
  reason: string;
  effect_kind?: "consequence" | "execution";
  status: "pending" | "resolved";
  created_turn: number;
  resolved_turn: number | null;
}

export interface GameDetail {
  game: Game;
  history: TurnResult[];
  echoes: EchoRecord[];
}

export interface EmperorPortrait {
  state: "ready";
  game_id: string;
  game_revision: number;
  generated_at: string;
  candidate_count: number;
  emperor: { id: string; name: string; dynasty: string; era: string; facts: string[]; sources: { title: string; url: string }[] };
  review: { emperor_id: string; biography: string; reign_title?: string; historian_comment?: string; referenced_turns?: number[] };
}

export interface HealthResponse {
  status: string;
  llm_mode: "live" | "fixture";
}

export interface AcceptedResponse {
  kind: "accepted";
  game: Game;
  result: TurnResult;
  policy_statuses?: Record<string, NonNullable<TurnResult["policy_status"]>>;
}

export type WarningType = "anachronism" | "multiple_goals" | "not_policy" | "unclear";

export interface ClarificationResponse {
  kind: "clarification";
  warning_type: WarningType;
  game: Game;
  message: string;
}

export interface DiplomacySession {
  id: string; sequence: number; turn: number; action: string; text: string; summary: string;
  proposal?: TreatyReport | null; battle?: WarReport | null; remaining_policy?: string;
  state_diff: GameState;
  reply?: {decision:'accepted'|'rejected'|'counter';reason:string;
    previous_terms:Record<'cities'|'treasury'|'grain',number>|null;
    requested_terms:Partial<Record<'cities'|'treasury'|'grain',number>>|null;
    offered_terms:Record<'cities'|'treasury'|'grain',number>;
    changes:Record<'cities'|'treasury'|'grain',number>|null}|null;
}
export interface DiplomacyResponse {kind:'diplomacy'; game:Game; session:DiplomacySession; remaining_policy:string}
export type SubmitResponse = AcceptedResponse | ClarificationResponse | DiplomacyResponse;

export interface ApiErrorBody {
  code: string;
  message: string;
  retryable?: boolean;
}

export class ApiError extends Error {
  status: number;
  code: string;
  retryable: boolean;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.retryable = body.retryable ?? false;
  }
}

export const YEARS_PER_TURN = 3;
export const TOTAL_TURNS = 8;
export const TOTAL_YEARS = YEARS_PER_TURN * TOTAL_TURNS;

const YEAR_NAMES = [
  "元", "二", "三", "四", "五", "六", "七", "八", "九", "十",
  "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
  "二十一", "二十二", "二十三", "二十四",
];

export function periodName(turnNo: number): string {
  const turn = Math.min(Math.max(turnNo, 1), TOTAL_TURNS);
  const startYear = (turn - 1) * YEARS_PER_TURN + 1;
  const endYear = startYear + YEARS_PER_TURN - 1;
  return `承和${YEAR_NAMES[startYear - 1]}年至${YEAR_NAMES[endYear - 1]}年`;
}

export const SPEAKER_INFO: Record<
  SpeakerId,
  { name: string; role: string; channel: string }
> = {
  tian_bo: { name: "田伯", role: "乡老", channel: "民间陈情" },
  song_zhiyuan: { name: "宋知远", role: "商帮会首", channel: "商路来报" },
  gu_tingzhang: { name: "顾廷章", role: "士绅代表", channel: "地方呈报" },
};

export const ADVISOR_INFO = { name: "沈砚", role: "御前辅臣" };
