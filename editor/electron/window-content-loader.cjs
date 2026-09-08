function isAbortedNavigation(error) {
  return String(error).includes('ERR_ABORTED')
}

async function loadWindowContent(window, load, showError, logError = console.error) {
  try {
    await load()
    return true
  } catch (error) {
    if (!window || window.isDestroyed() || isAbortedNavigation(error)) {
      return false
    }
    try {
      await showError(error)
    } catch (displayError) {
      if (!isAbortedNavigation(displayError)) {
        logError('Failed to show renderer load error:', displayError)
      }
    }
    return false
  }
}

/** Show an existing single-instance window and optionally reload recovered development content. */
async function restoreExistingWindow(window, reload) {
  if (!window || window.isDestroyed()) return false
  if (window.isMinimized()) window.restore()
  window.show()
  window.focus()
  await reload()
  return true
}

module.exports = { isAbortedNavigation, loadWindowContent, restoreExistingWindow }
