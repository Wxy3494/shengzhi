/** Decorative codex artwork, not an authenticated historical portrait. */
export default function EmperorIllustration({id,title}:{id:string;title:string}) {
  const qing=id.startsWith('qing_'),female=id==='wu_zetian';
  const robe=qing?'#74552f':female?'#833939':id.startsWith('ming_')?'#933f2f':'#4d6260';
  return <svg className="codex-illustration" viewBox="0 0 340 580" role="img" aria-label={`${title}图鉴绘影`}>
    <rect width="340" height="580" fill="#d7be8e"/><path d="M18 0v580M322 0v580" stroke="#9b7043"/>
    <circle cx="170" cy="170" r="112" fill="#e8d4a8" stroke="#b38b54"/>
    <path d="M18 455V345h34v-24h236v24h34v110M32 344h276M50 386h240" fill="none" stroke="#ac946a" strokeWidth="3"/>
    <path d="M68 580 83 302Q100 267 145 263h50q44 4 62 39l17 278" fill={robe} stroke="#5b4231" strokeWidth="3"/>
    <path d="m104 282 66 57 66-57-25 149-41 45-41-45Z" fill="#a97e43" stroke="#d7b66d" strokeWidth="3"/>
    <path d="m106 295 64 63 64-63M90 498q80-44 160 0" fill="none" stroke="#d8b76e" strokeWidth="4"/>
    <ellipse cx="170" cy="207" rx="49" ry="65" fill="#c89768" stroke="#765035" strokeWidth="2"/>
    <path d="M123 191q-5-58 47-60 53 2 47 60l-12-27h-70Z" fill="#332c26"/>
    <path d="m143 204 13-3m28 0 13 3M168 209l-4 24 11 1m-20 17q15 8 30-1" fill="none" stroke="#6e4330" strokeWidth="3"/>
    {!female&&<path d="m151 249 19 10 20-10-3 33-17 14-15-14Z" fill="#443329"/>}
    {qing?<><path d="M112 157q6-60 58-68 52 8 58 68Z" fill="#3b3430"/><path d="M110 151h120l-5 18H115Z" fill="#902e27"/><circle cx="170" cy="89" r="9" fill="#be8134"/></>
      :<><path d="M121 156v-48h98v48Z" fill="#302b28"/><path d="M109 108h122l-9-18H118Z" fill="#b08942"/>{[125,143,161,179,197,215].map(x=><path key={x} d={`M${x} 108v54`} stroke="#d1b166" strokeWidth="3"/>)}</>}
    <path d="m87 361 43 63 33-29 26 18 29-19 38-29-12 118H95Z" fill={robe} stroke="#b48c51" strokeWidth="3"/>
    <path d="m147 403 22-9 22 19-21 11Z" fill="#c89768"/>
    <rect x="155" y="430" width="30" height="53" rx="4" fill="#c9a75d"/><path d="M163 444h14m-14 10h14m-14 10h14" stroke="#866133"/>
  </svg>;
}
