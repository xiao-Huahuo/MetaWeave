/**
 * Adds decorative icons to sanitized Agent Markdown links, including streaming fragments.
 * Reuses Material file icons locally and requests only website origins from faviconV2.
 */
import globeIcon from '@/assets/icons/svg/dsh/globe-outline14.svg?url'
import { createStaticMorphIcon } from '@/components/common/iconRegistry'
import { materialFileIconForNode } from '../materialFileIcons'

/** Adds one icon per link without changing its label or existing navigation. */
export function decorateMarkdownLinks(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('a[href], .source-file-link').forEach((link) => {
    if (link.closest('pre, code') || link.querySelector('img, .markdown-link-icon')) return
    const href = link.dataset.sourceUri ?? link.getAttribute('href') ?? ''
    if (!href || href.startsWith('#') || /^(?:mailto|tel):/i.test(href)) return
    const absoluteFile = /^(?:file:|session-upload:|[a-z]:(?:[\\/]|%5c|%2f))/i.test(href)
    if (!absoluteFile && /^[a-z][a-z\d+.-]*:/i.test(href) && !/^https?:/i.test(href)) return

    let url: URL
    try {
      url = new URL(absoluteFile ? href.replace(/\\/g, '/') : href, window.location.href)
    } catch {
      return
    }
    const knowledgePath = url.pathname === '/knowledge/files/raw' ? url.searchParams.get('path') : null
    const isWeb = !absoluteFile && !link.dataset.sourceUri && !knowledgePath && /^(?:https?:)?\/\//i.test(href)
    let path = knowledgePath ?? (absoluteFile ? href.replace(/^file:\/\//i, '') : url.pathname)
    try { path = decodeURIComponent(path) } catch { /* Keep malformed percent escapes as literal filenames. */ }
    path = path.replace(/[?#].*$/, '').replace(/:\d+(?::\d+)?$/, '').replace(/\\/g, '/')
    const name = path.split('/').filter(Boolean).pop() ?? path

    const icon = document.createElement('span')
    icon.className = 'markdown-link-icon'
    icon.setAttribute('aria-hidden', 'true')
    if (isWeb) {
      const fallback = document.createElement('span')
      fallback.className = 'markdown-link-icon__fallback'
      fallback.style.maskImage = `url("${globeIcon}")`
      icon.appendChild(fallback)
    } else {
      icon.appendChild(createStaticMorphIcon('file', 16))
    }

    const image = document.createElement('img')
    image.alt = ''
    image.setAttribute('referrerpolicy', 'no-referrer')
    image.addEventListener('load', () => icon.classList.add('is-loaded'), { once: true })
    image.addEventListener('error', () => image.remove(), { once: true })
    image.src = isWeb
      ? `https://t0.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=${encodeURIComponent(url.origin)}&size=32&drop_404_icon=true`
      : materialFileIconForNode({ name, path, isDir: path.endsWith('/') }).src
    icon.appendChild(image)
    link.prepend(icon)
  })
}
