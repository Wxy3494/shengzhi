import type { SpeakerId, TurnResult } from "./game";

export type ChatMessage =
  | {
      kind: "edict";
      id: string;
      text: string;
      status: "pending" | "accepted";
      turnNo: number;
    }
  | { kind: "advisor"; id: string; text: string; turnNo: number }
  | { kind: "reaction"; id: string; speaker: SpeakerId; text: string; turnNo: number }
  | { kind: "error"; id: string; text: string }
  | { kind: "turn-card"; id: string; turnNo: number; result: TurnResult };

export function buildChatFromHistory(history: TurnResult[]): ChatMessage[] {
  const messages: ChatMessage[] = [];
  for (const result of history) {
    messages.push({
      kind: "edict",
      id: `edict-${result.turn_no}`,
      text: result.raw_text,
      status: "accepted",
      turnNo: result.turn_no,
    });
    messages.push({
      kind: "turn-card",
      id: `card-${result.turn_no}`,
      turnNo: result.turn_no,
      result,
    });
  }
  return messages;
}
