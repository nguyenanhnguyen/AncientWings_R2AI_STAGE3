"""Printing that survives a console which cannot encode the text.

Reports here are written in Vietnamese and the JSON summaries keep their diacritics, but a Windows
console still defaults to cp1252 and raises on the first accented character. The block CLIs call
`sys.stdout.reconfigure(encoding='utf-8')` in their `main()`, which covers normal command-line
use; this covers the rest — the same functions called from a notebook, a test, or another script
that never reconfigured its stdout. Losing a diacritic in a progress line beats losing the run.
"""
import sys


def emit(text=''):
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, 'encoding', None) or 'ascii'
        print(text.encode(encoding, 'backslashreplace').decode(encoding), flush=True)
