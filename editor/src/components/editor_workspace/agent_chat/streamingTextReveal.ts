/**
 * Streaming assistant text reveal helper.
 *
 * Usage:
 * Decorates visible words in a freshly parsed active Markdown fragment while
 * preserving animation timestamps across the fragment rebuilds required by
 * incremental Markdown parsing.
 */

export const STREAM_REVEAL_DURATION_MS = 180
export const STREAM_REVEAL_SWEEP_MS = 90
const STREAM_REVEAL_MIN_GAP_MS = 18

export interface StreamRevealToken {
  text: string
  startsAt: number
}

interface TextNodePlan {
  node: Text
  segments: string[]
}

interface WordSegmenter {
  segment(text: string): Iterable<{ segment: string }>
}

type WordSegmenterConstructor = new (
  locales?: string | string[],
  options?: { granularity: 'word' },
) => WordSegmenter

const Segmenter = (Intl as unknown as { Segmenter?: WordSegmenterConstructor }).Segmenter
const wordSegmenter = Segmenter ? new Segmenter(undefined, { granularity: 'word' }) : null

/** Return visible word and spacing segments without changing their text. */
function segmentText(text: string): string[] {
  return wordSegmenter
    ? Array.from(wordSegmenter.segment(text), (part) => part.segment)
    : text.match(/\s+|./gu) ?? []
}

/** Exclude duplicate/accessibility-only math and non-visible document text. */
function isRevealableTextNode(node: Text): boolean {
  const parent = node.parentElement
  return Boolean(
    node.nodeValue
    && parent
    && !parent.closest('script, style, svg, .katex'),
  )
}

/** Count the unchanged visible-token prefix retained from the previous parse. */
function commonTokenPrefix(previous: StreamRevealToken[], next: string[]): number {
  const limit = Math.min(previous.length, next.length)
  let index = 0
  while (index < limit && previous[index]?.text === next[index]) index += 1
  return index
}

/**
 * Wrap visible words and assign a bounded left-to-right reveal schedule.
 * Existing tokens resume from their original timestamp after DOM reconstruction;
 * only the changed suffix receives fresh timestamps.
 */
export function decorateStreamingText(
  fragment: DocumentFragment,
  previous: StreamRevealToken[],
  now: number,
  animate: boolean,
): { tokens: StreamRevealToken[]; deadline: number } {
  const walker = document.createTreeWalker(fragment, NodeFilter.SHOW_TEXT)
  const plans: TextNodePlan[] = []
  const visibleTokens: string[] = []
  let current = walker.nextNode()
  while (current) {
    if (isRevealableTextNode(current as Text)) {
      const segments = segmentText(current.nodeValue ?? '')
      plans.push({ node: current as Text, segments })
      for (const segment of segments) {
        if (segment.trim()) visibleTokens.push(segment)
      }
    }
    current = walker.nextNode()
  }

  const prefixLength = commonTokenPrefix(previous, visibleTokens)
  const newTokenCount = visibleTokens.length - prefixLength
  const latestPreviousStart = previous
    .slice(0, prefixLength)
    .reduce((latest, token) => Math.max(latest, token.startsAt), Number.NEGATIVE_INFINITY)
  const batchStart = animate
    ? Math.max(now, latestPreviousStart + STREAM_REVEAL_MIN_GAP_MS)
    : now - STREAM_REVEAL_DURATION_MS
  const tokens: StreamRevealToken[] = []
  let wordIndex = 0

  for (const plan of plans) {
    const replacement = document.createDocumentFragment()
    for (const segment of plan.segments) {
      if (!segment.trim()) {
        replacement.append(document.createTextNode(segment))
        continue
      }
      const newIndex = wordIndex - prefixLength
      const sweepOffset = newTokenCount > 1
        ? (Math.max(0, newIndex) / (newTokenCount - 1)) * STREAM_REVEAL_SWEEP_MS
        : 0
      const startsAt = wordIndex < prefixLength
        ? previous[wordIndex]?.startsAt ?? now
        : batchStart + sweepOffset
      const span = document.createElement('span')
      span.textContent = segment
      if (animate && now < startsAt + STREAM_REVEAL_DURATION_MS) {
        span.className = 'stream-reveal-word'
        span.style.setProperty('--stream-reveal-delay', `${Math.round(startsAt - now)}ms`)
      }
      replacement.append(span)
      tokens.push({ text: segment, startsAt })
      wordIndex += 1
    }
    plan.node.replaceWith(replacement)
  }

  const deadline = animate
    ? tokens.reduce((latest, token) => Math.max(latest, token.startsAt + STREAM_REVEAL_DURATION_MS), now)
    : now
  return { tokens, deadline }
}
