"""HTTP layer (docs/API.md): request guard, security headers, error envelope, routes and
the static frontend. Handlers are thin: they parse HTTP input, call the domain functions
and map their results and errors.
"""
