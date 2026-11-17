/** Model and historical risk strings may already contain their connectors. */
export function formatRiskSentence(condition: string, consequence: string): string {
  const when = condition.trim().replace(/[，,；;。]+$/, "");
  const then = consequence.trim().replace(/^[，,；;]+/, "");
  if (!when) return then;
  if (!then) return when;
  const prefix = /^(若|如果|倘若|假如|一旦|如若)/.test(when) ? "" : "若";
  const possibility = /^(可能|或将|恐|将|会|易|有可能|则|便|就)/.test(then) ? "" : "可能";
  return `${prefix}${when}，${possibility}${then}`;
}
