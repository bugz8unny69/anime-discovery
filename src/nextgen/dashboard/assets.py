"""Exact public asset allowlist. Never serve a caller-supplied filesystem path."""
from pathlib import Path

ROOT=Path(__file__).with_name('static')
FILES={
    '/':('index.html','text/html; charset=utf-8'),
    '/recognized':('index.html','text/html; charset=utf-8'),
    '/jobs':('index.html','text/html; charset=utf-8'),
    '/settings':('index.html','text/html; charset=utf-8'),
    '/assets/dashboard.css':('dashboard.css','text/css; charset=utf-8'),
    '/assets/dashboard.js':('dashboard.js','text/javascript; charset=utf-8'),
}
CSP=("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
     "base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'")


def load_assets():
    """Trusted, bounded source assets loaded once at process construction."""
    result={}
    for route,(name,mime) in FILES.items():
        content=(ROOT/name).read_bytes()
        if len(content)>262144:raise ValueError('Dashboard asset exceeds its bound.')
        result[route]=(mime,content)
    return result
