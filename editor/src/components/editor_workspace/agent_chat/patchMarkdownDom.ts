/**
 * Patches already-sanitized streaming Markdown without discarding its stable DOM.
 * Pass only nodes produced by the shared Markdown sanitizer; this helper is not
 * an HTML trust boundary. Completed blocks outside `previous` remain untouched.
 */
/** Bound the mutable suffix so long paragraph line breaking can reuse its prefix. */
const MAX_STREAM_TEXT_CHARS = 1024

/** Reuses matching nodes and patches only changed sanitized attributes/text. */
export function patchMarkdownDom(parent: Node, previous: Node[], incoming: Node[]): Node[] {
  const result: Node[] = []
  let previousIndex = 0
  for (let index = 0; index < incoming.length; index += 1) {
    const next = incoming[index]!
    const current = previous[previousIndex++]
    if (!current) {
      parent.appendChild(next)
      result.push(next)
      continue
    }
    if (current instanceof Text && next instanceof Text) {
      const texts = [current]
      while (previous[previousIndex] instanceof Text) {
        texts.push(previous[previousIndex++] as Text)
      }
      const prefix = texts.map((text) => text.data).join('')
      if (next.data.startsWith(prefix)) {
        const delta = next.data.slice(prefix.length)
        const tail = texts[texts.length - 1]!
        if (delta && tail.length + delta.length <= MAX_STREAM_TEXT_CHARS) {
          tail.appendData(delta)
        } else if (delta) {
          // Keep long laid-out text immutable. Changing a 50k-character Text
          // invalidates Chromium's cached line breaking for its entire prefix.
          const addition = document.createTextNode(delta)
          parent.insertBefore(addition, tail.nextSibling)
          texts.push(addition)
        }
        result.push(...texts)
      } else {
        current.data = next.data
        for (const stale of texts.slice(1)) parent.removeChild(stale)
        result.push(current)
      }
      continue
    }
    if (current.nodeType !== next.nodeType || current.nodeName !== next.nodeName) {
      parent.replaceChild(next, current)
      result.push(next)
      continue
    }
    // Native subtree comparison skips unchanged highlighted tokens and rows.
    if (current.isEqualNode(next)) {
      result.push(current)
      continue
    }
    // Decorated icons own load/error handlers that close over their container.
    // Keep that container for the same resource, including its loaded/fallback state.
    if (current instanceof Element && next instanceof Element
      && current.matches('.markdown-link-icon') && next.matches('.markdown-link-icon')) {
      const source = current.getAttribute('data-icon-src')
      if (source && source === next.getAttribute('data-icon-src')) {
        result.push(current)
      } else {
        parent.replaceChild(next, current)
        result.push(next)
      }
      continue
    }
    if (current.nodeType === Node.TEXT_NODE || current.nodeType === Node.COMMENT_NODE) {
      const text = next.nodeValue ?? ''
      if (current.nodeValue !== text) {
        current.nodeValue = text
      }
    } else if (current instanceof Element && next instanceof Element) {
      for (const attribute of Array.from(current.attributes)) {
        if (!next.hasAttribute(attribute.name)) current.removeAttribute(attribute.name)
      }
      for (const attribute of Array.from(next.attributes)) {
        if (current.getAttribute(attribute.name) !== attribute.value) {
          current.setAttribute(attribute.name, attribute.value)
        }
      }
      patchMarkdownDom(current, Array.from(current.childNodes), Array.from(next.childNodes))
    }
    result.push(current)
  }
  for (const stale of previous.slice(previousIndex)) parent.removeChild(stale)
  return result
}
