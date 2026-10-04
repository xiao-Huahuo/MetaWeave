"""Request-scoped immutable authenticated identity shared by REST, gRPC and services.

Transport guards set this value only after AuthService validation and reset the
returned token in a finally block. Background jobs supply their own explicit owner.
"""

from contextvars import ContextVar

from agent_service.services.auth.service import AuthSession

current_identity: ContextVar[AuthSession | None] = ContextVar("authenticated_account_identity", default=None)
