"""The read-only MCP server, mounted at `/mcp` inside the backend (official `mcp` SDK, HTTP transport).

Every request needs the same bearer token as the REST API. Each tool call resolves the user again from that token
and checks trip membership itself, so access never depends on what the model says. No tool changes anything.
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.db import get_engine
from app.mcp_server import tools
from app.models import AuthToken, User

logger = logging.getLogger("app.mcp")

# The tools the server offers (a test checks this list, so adding a modifying tool cannot go unnoticed).
TOOL_NAMES = tuple(tools.TOOL_DESCRIPTIONS)


def user_from_authorization(session: Session, header: str | None) -> User | None:
    """The user a `Bearer <token>` header belongs to, or None."""
    scheme, _, token = (header or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return session.scalar(
        select(User).join(AuthToken, AuthToken.user_id == User.id).where(AuthToken.token == token.strip())
    )


async def run_tool(ctx: Context, name: str, function, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Authenticate the call from its bearer token, run the (blocking) tool in a thread and report its outcome."""
    request = ctx.request_context.request
    header = request.headers.get("authorization") if request is not None else None
    request_id = getattr(getattr(request, "state", None), "request_id", "-")

    def work() -> dict[str, Any]:
        with Session(get_engine(), expire_on_commit=False) as session:
            user = user_from_authorization(session, header)
            if user is None:
                raise tools.ToolFailure("Authentication is required.")
            return function(session, user, *args, **kwargs)

    started = time.monotonic()
    try:
        result = await anyio.to_thread.run_sync(work)
    except tools.ToolFailure as exc:
        logger.info("mcp tool %s failed in %d ms: %s", name, (time.monotonic() - started) * 1000, exc)
        raise ToolError(str(exc)) from exc
    except Exception:
        logger.exception("mcp tool %s crashed (request %s)", name, request_id)
        raise ToolError("The tool failed unexpectedly. Try again later.") from None
    logger.info("mcp tool %s ok in %d ms", name, (time.monotonic() - started) * 1000)
    return result


def build_server() -> FastMCP:
    server = FastMCP(
        "travel-planner",
        instructions="Read-only tools for a travel planning application. They read trips the caller belongs to and "
        "search offers; nothing here books or changes anything.",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        # The bearer token protects the endpoint; the host check meant for local-only servers would block Docker names.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    describe = tools.TOOL_DESCRIPTIONS

    @server.tool(name="get_trip", description=describe["get_trip"])
    async def get_trip(trip_id: str, ctx: Context) -> dict[str, Any]:
        return await run_tool(ctx, "get_trip", tools.get_trip, trip_id)

    @server.tool(name="get_itinerary", description=describe["get_itinerary"])
    async def get_itinerary(trip_id: str, ctx: Context) -> dict[str, Any]:
        return await run_tool(ctx, "get_itinerary", tools.get_itinerary, trip_id)

    @server.tool(name="get_budget", description=describe["get_budget"])
    async def get_budget(trip_id: str, ctx: Context) -> dict[str, Any]:
        return await run_tool(ctx, "get_budget", tools.get_budget, trip_id)

    @server.tool(name="get_bookings", description=describe["get_bookings"])
    async def get_bookings(trip_id: str, ctx: Context) -> dict[str, Any]:
        return await run_tool(ctx, "get_bookings", tools.get_bookings, trip_id)

    @server.tool(name="search_options", description=describe["search_options"])
    async def search_options(
        trip_id: str,
        category: str,
        destination: str,
        ctx: Context,
        origin: str | None = None,
        starts_on: str | None = None,
        ends_on: str | None = None,
        travelers: int | None = None,
        supplier: str | None = None,
    ) -> dict[str, Any]:
        """category: transport, accommodation or activity. destination must be one of the trip's destinations.
        origin is required for transport. starts_on and ends_on are YYYY-MM-DD and default to the trip dates;
        travelers defaults to the trip's travelers; supplier optionally limits the search to one supplier."""
        request_id = getattr(getattr(ctx.request_context.request, "state", None), "request_id", "-")
        return await run_tool(
            ctx,
            "search_options",
            tools.search_options,
            trip_id,
            category,
            destination,
            origin,
            starts_on,
            ends_on,
            travelers,
            supplier,
            request_id=request_id,
        )

    return server


class McpGateway:
    """The ASGI app behind `/mcp`: answers 401 without a valid token, otherwise hands over to the MCP server.

    The MCP server (and its session manager, which can only run once) is created for each application lifespan, so
    tests and restarts start a fresh one.
    """

    def __init__(self) -> None:
        self.app: Any = None

    async def __call__(self, scope, receive, send) -> None:
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}

        def lookup() -> bool:
            with Session(get_engine()) as session:
                return user_from_authorization(session, headers.get("authorization")) is not None

        if self.app is None:
            response = JSONResponse(
                {"code": "MCP_UNAVAILABLE", "message": "The MCP server is not running.", "requestId": None, "details": None},
                status_code=503,
            )
        elif not await anyio.to_thread.run_sync(lookup):
            request_id = scope.get("state", {}).get("request_id")
            response = JSONResponse(
                {"code": "UNAUTHORIZED", "message": "Missing or invalid authentication token.", "requestId": request_id, "details": None},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        else:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)


gateway = McpGateway()


def mount(app) -> None:
    """Add the `/mcp` route to the FastAPI app."""
    app.router.routes.append(Route("/mcp", endpoint=gateway, methods=["GET", "POST", "DELETE"]))


@asynccontextmanager
async def running():
    """Start the MCP server for the lifetime of the application."""
    server = build_server()
    server.streamable_http_app()  # creates the session manager
    async with server.session_manager.run():
        gateway.app = StreamableHTTPASGIApp(server.session_manager)
        try:
            yield
        finally:
            gateway.app = None
