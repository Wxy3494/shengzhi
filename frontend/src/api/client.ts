import type {
  ApiErrorBody,
  GameDetail,
  HealthResponse,
  SubmitResponse,
  EmperorPortrait,
  DiplomacyResponse,
} from "../types/game";
import { ApiError } from "../types/game";
import type { OpeningBrief } from "../types/game";

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/+$/, "");

async function request<T>(path: string, init?: RequestInit, timeoutMs = 60_000): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
      signal: controller.signal,
    });
    if (response.ok) {
      try { return (await response.json()) as T; }
      catch (error) {
        if (controller.signal.aborted) throw error;
        throw new ApiError(response.status, {code:"INVALID_RESPONSE", message:"奏报响应不完整，请重试。", retryable:true});
      }
    }
    let body: ApiErrorBody;
    try {
      const payload = await response.json();
      body = (payload?.detail && typeof payload.detail === "object" && !Array.isArray(payload.detail)
        ? payload.detail : payload) as ApiErrorBody;
      if (Array.isArray(payload?.detail)) body = {code:"VALIDATION_ERROR",message:"圣旨格式有误，请检查内容与长度。",retryable:false};
    } catch (error) {
      if (controller.signal.aborted) throw error;
      body = {code:`HTTP_${response.status}`, message:`游戏服务暂不可用（HTTP ${response.status}）。`};
    }
    if (!body || typeof body !== "object" || !body.code) {
      body = {code:`HTTP_${response.status}`,message:body?.message || `请求失败（HTTP ${response.status}）。`};
    }
    const transient = response.status === 408 || response.status === 429 || response.status >= 500;
    body.retryable = transient && body.retryable !== false;
    throw new ApiError(response.status, body);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(0, controller.signal.aborted
      ? {code:"REQUEST_TIMEOUT",message:"等待奏报超时，尚不能确认本回合是否已结算。",retryable:true}
      : {code:"NETWORK_ERROR",message:"无法连接游戏服务，请确认游戏服务已启动、网络连接正常。",retryable:true});
  } finally { window.clearTimeout(timeout); }
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

export interface EmperorEntry {id:string;name:string;dynasty:string;era:string;themes:string[];facts:string[];sources:{title:string;url:string}[]}
export function getEmperorLibrary():Promise<{catalog_version:number;count:number;emperors:EmperorEntry[]}>{return request('/api/emperors');}

export function createGame(): Promise<GameDetail> {
  return request<GameDetail>("/api/games", { method: "POST" });
}

export function getGame(gameId: string, timeoutMs = 60_000): Promise<GameDetail> {
  return request<GameDetail>(`/api/games/${encodeURIComponent(gameId)}`, undefined, timeoutMs);
}

export interface PolicyPreview {
  game_id: string; revision: number; turn: number; policy_text: string; execution: string | null;
  intent: {category: string; action: string; region: string}; methods: string[]; prohibitions: string[];
  base_effect: {people: number; treasury: number; grain: number}; notes: string[];
  due_events: {id: string; name: string; turn: number}[]; due_echoes: {id: string; reason: string}[];
  treaty?: {direction: 'pay' | 'receive'; terms: {cities: number; treasury: number; grain: number}} | null;
}
export function previewPolicy(gameId: string, revision: number, text: string): Promise<PolicyPreview> {
  return request(`/api/games/${encodeURIComponent(gameId)}/preview`, {method:'POST',body:JSON.stringify({expected_revision:revision,policy_text:text})});
}

export function submitTurn(
  gameId: string,
  body: {
    request_id: string;
    expected_revision: number;
    policy_text: string;
    expected_turn?: number;
  }
): Promise<SubmitResponse> {
  return request<SubmitResponse>(`/api/games/${encodeURIComponent(gameId)}/turns`, {
    method: "POST",
    body: JSON.stringify({...body, expectedTurn: body.expected_turn ?? body.expected_revision + 1, idempotencyKey: body.request_id}),
  });
}

export const MAX_TURN_RETRIES = 3;
export interface TurnRetryProgress { retry: number; maxRetries: number; reason: string }
export type TurnDelivery = SubmitResponse | {kind:"recovered"; detail:GameDetail};
type TurnBody = Parameters<typeof submitTurn>[1];
const pause = (ms: number) => new Promise<void>(resolve => window.setTimeout(resolve, ms));

/** One initial attempt plus three retries, with the exact same id and revision. */
export async function submitTurnWithRetry(
  gameId: string, body: TurnBody, onRetry?: (progress: TurnRetryProgress) => void,
  wait: (ms: number) => Promise<void> = pause,
): Promise<TurnDelivery> {
  // Freeze the payload so edits during a retry can never change an idempotent request.
  const original = {...body};
  for (let attempt = 0; ; attempt++) {
    try { return await submitTurn(gameId, original); }
    catch (error) {
      if (!(error instanceof ApiError) || !error.retryable) throw error;
      // The reply may have been lost after commit. Read before sending it again.
      const fresh = await getGame(gameId, 5_000).catch(() => null);
      if (fresh && fresh.game.revision > original.expected_revision) {
        const session=fresh.game.diplomacy?.records?.find(s=>s.id===original.request_id);
        if(session)return {kind:'diplomacy',game:fresh.game,session,remaining_policy:session.remaining_policy ?? ''};
        const settled = fresh.history.some(item => item.turn_no === (original.expected_turn ?? original.expected_revision + 1) && item.raw_text === original.policy_text);
        if (settled) return {kind:"recovered",detail:fresh};
        throw new ApiError(409,{code:"STALE_REVISION",message:"存档已更新，已停止重试，请核对最新奏报。",retryable:false});
      }
      if (attempt >= MAX_TURN_RETRIES) throw error;
      onRetry?.({retry:attempt+1,maxRetries:MAX_TURN_RETRIES,reason:error.message});
      await wait(error.code==='MODEL_OUTPUT_INVALID'?250:1_000 * 2 ** attempt);
    }
  }
}

export interface DiplomacyBody {request_id:string; expected_revision:number; action:'accept'|'reject'|'counter'; text:string; proposal_id?:string}
export async function negotiateNow(gameId:string,body:DiplomacyBody):Promise<DiplomacyResponse> {
  const original={...body};
  for(let attempt=0;;attempt++) {
    try{return await request(`/api/games/${encodeURIComponent(gameId)}/diplomacy`,{method:'POST',body:JSON.stringify({...original,idempotencyKey:original.request_id})});}
    catch(error) {
      if(!(error instanceof ApiError) || !error.retryable)throw error;
      const fresh=await getGame(gameId,5000).catch(()=>null);
      const session=fresh?.game.diplomacy?.records?.find(s=>s.id===original.request_id);
      if(fresh && session)return {kind:'diplomacy',game:fresh.game,session,remaining_policy:session.remaining_policy ?? ''};
      if(fresh && fresh.game.revision>original.expected_revision)throw new ApiError(409,{code:'STALE_REVISION',message:'议和条件已更新，请重新核对。',retryable:false});
      if(attempt>=MAX_TURN_RETRIES)throw error;
      await pause(error.code==='TREATY_MODEL_FAILED'?250:1000*2**attempt);
    }
  }
}

const pendingPortraits = new Map<string, Promise<EmperorPortrait>>();
const pendingOpenings = new Map<string, Promise<OpeningBrief>>();
export function getOpeningBriefing(gameId: string): Promise<OpeningBrief> {
  const existing = pendingOpenings.get(gameId);
  if (existing) return existing;
  const promise = request<OpeningBrief>(`/api/games/${encodeURIComponent(gameId)}/opening`, {method: "POST"})
    .finally(() => pendingOpenings.delete(gameId));
  pendingOpenings.set(gameId, promise);
  return promise;
}

export function getEmperorPortrait(gameId: string): Promise<EmperorPortrait> {
  const existing = pendingPortraits.get(gameId);
  if (existing) return existing;
  const promise = request<EmperorPortrait>(`/api/games/${encodeURIComponent(gameId)}/emperor`, {
    method: "POST",
  }).finally(() => pendingPortraits.delete(gameId));
  pendingPortraits.set(gameId, promise);
  return promise;
}
