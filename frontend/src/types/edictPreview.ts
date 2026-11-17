/** Literal draft summary. Never invent execution details or predicted effects. */
export function previewEdict(text: string) {
  const clauses = text.trim()
    .replace(/(?:并且|且|并)(?=不得|禁止|严禁|不强征|不搜刮|不夺|勿|毋)/gu, '；')
    .split(/[，,。；;\n]+|、(?=不|勿|毋|禁止|严禁)/u).map(s => s.trim()).filter(Boolean);
  const prohibition = /^(?:且|并且|并|一律|务必|绝|坚决)?\s*(?:不|不得|禁止|严禁|勿|毋|切勿|杜绝|避免|停止|暂停|拒绝)/u;
  const forbidden = clauses.filter(s => prohibition.test(s));
  const positive = clauses.filter(s => !prohibition.test(s));
  const methods = positive.slice(1);
  const first = positive[0] ?? '';
  const explicitMethod = first.match(/(?:通过|采用|采取|以)(.+?)(?:方式|办法|之法)/u)?.[0];
  if (explicitMethod) methods.unshift(explicitMethod);
  else if (/雇工|雇佣/u.test(first)) methods.unshift('雇工办理');
  return {
    goal: first || '尚未写明要实施的主目标，请返回补充。',
    methods,
    forbidden,
  };
}
