import type { Game } from "./game";

export function takeCrisisNotices(game: Game, storage: Pick<Storage, "getItem" | "setItem">) {
  return (game.realm?.warnings ?? []).filter(warning => {
    if (warning.threshold !== 75 && warning.threshold !== 90) return false;
    const key = `shengzhi.crisisNotice.${game.id}.${warning.id}.${warning.threshold}`;
    try {
      if (storage.getItem(key)) return false;
      storage.setItem(key, "shown");
    } catch { /* The mounted component also deduplicates the current revision. */ }
    return true;
  });
}
