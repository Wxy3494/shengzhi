/** Hide removed legacy presentation copy without rewriting saved results. */
export function displayBattleText(text: string): string {
  return text.replace(/[；;]?\s*尚未同意任何割城或赔款[。.]?/gu, '。');
}
