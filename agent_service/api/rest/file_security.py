"""Response policy for authenticated user files that may contain active document content.

SVG/HTML remain intact, while a top-level navigation receives an opaque sandboxed
origin with scripts disabled. Image subresources keep their existing MIME types.
"""


def untrusted_file_headers() -> dict[str, str]:
    """Return fresh header values so response code cannot mutate shared policy state."""
    return {
        "Content-Security-Policy": "sandbox; default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    }
