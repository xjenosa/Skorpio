import type { ReactNode } from 'react'

// Shared light-markdown renderer used by every Final report's executive
// summary. Handles paragraphs, bullet lists, `#` / `##` / `###` headers,
// `**bold**`, `*italic*`, and `` `code` ``. Lifted out of FinalReport.tsx
// so all 5 pipelines render their summary the same way (the agents emit
// markdown markers in every pipeline; only siting used to render them).

function renderInline(text: string, baseKey: string): ReactNode {
  const out: ReactNode[] = []
  let rem = text
  let k = 0
  while (rem.length > 0) {
    let m = rem.match(/^\*\*([^*]+)\*\*/)
    if (m) {
      out.push(<strong key={`${baseKey}-${k++}`}>{m[1]}</strong>)
      rem = rem.slice(m[0].length)
      continue
    }
    m = rem.match(/^\*([^*]+)\*/)
    if (m) {
      out.push(<em key={`${baseKey}-${k++}`}>{m[1]}</em>)
      rem = rem.slice(m[0].length)
      continue
    }
    m = rem.match(/^`([^`]+)`/)
    if (m) {
      out.push(<code key={`${baseKey}-${k++}`}>{m[1]}</code>)
      rem = rem.slice(m[0].length)
      continue
    }
    const next = rem.search(/[*`]/)
    if (next === -1) { out.push(rem); break }
    if (next === 0) { out.push(rem[0]); rem = rem.slice(1) }
    else { out.push(rem.slice(0, next)); rem = rem.slice(next) }
  }
  return out
}

export function renderMarkdown(text: string): ReactNode[] {
  return text
    .split(/\n\n+/)
    .map((raw, i) => {
      const block = raw.trim()
      if (!block) return null
      if (block.startsWith('### ')) return <h4 key={i}>{renderInline(block.slice(4), `h4-${i}`)}</h4>
      if (block.startsWith('## ')) return <h3 key={i}>{renderInline(block.slice(3), `h3-${i}`)}</h3>
      if (block.startsWith('# ')) return <h2 key={i}>{renderInline(block.slice(2), `h2-${i}`)}</h2>
      const lines = block.split('\n')
      if (lines.every((l) => l.trim().startsWith('- '))) {
        return (
          <ul key={i}>
            {lines.map((l, j) => (
              <li key={j}>{renderInline(l.trim().slice(2), `li-${i}-${j}`)}</li>
            ))}
          </ul>
        )
      }
      return <p key={i}>{renderInline(block, `p-${i}`)}</p>
    })
    .filter(Boolean) as ReactNode[]
}
