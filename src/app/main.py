"""FastAPI application factory.

Creates the app with tenant middleware, logging middleware, metrics middleware,
CORS, Sentry, lifespan events for database initialization, and the v1 API router.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import Response

from src.app.config import get_settings
from src.app.core.database import close_db, init_db
from src.app.core.monitoring import MetricsMiddleware, get_metrics_response, init_sentry
from src.app.core.redis import close_redis, get_redis_pool
from src.app.api.middleware.tenant import TenantAuthMiddleware
from src.app.api.middleware.logging import LoggingMiddleware, configure_structlog
from src.app.api.v1.router import router as v1_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: init DB and Sentry on startup, close on shutdown."""
    import structlog

    log = structlog.get_logger(__name__)
    settings = get_settings()
    configure_structlog()
    await init_db()

    # Initialize Sentry if DSN is configured
    if settings.SENTRY_DSN:
        init_sentry(dsn=settings.SENTRY_DSN, environment=settings.ENVIRONMENT.value)

    # ── Phase 2: Agent Orchestration Module Initialization ──────────────
    # All Phase 2 init is additive and failure-tolerant. Each module is
    # wrapped in its own try/except so a single failure (e.g., pgvector
    # not installed) does not prevent the application from starting.

    # Langfuse tracing (instruments LiteLLM callbacks)
    try:
        from src.app.observability.tracer import init_langfuse

        init_langfuse(settings)
    except Exception:
        log.warning("phase2.langfuse_init_failed", exc_info=True)

    # Session store (LangGraph checkpointer)
    try:
        from src.app.context.session import SessionStore

        session_store = SessionStore(settings.DATABASE_URL)
        await session_store.setup()
        app.state.session_store = session_store
        log.info("phase2.session_store_initialized")
    except Exception:
        log.warning("phase2.session_store_init_failed", exc_info=True)
        app.state.session_store = None

    # Long-term memory (pgvector)
    try:
        from src.app.context.memory import LongTermMemory

        long_term_memory = LongTermMemory(settings.DATABASE_URL)
        await long_term_memory.setup()
        app.state.long_term_memory = long_term_memory
        log.info("phase2.long_term_memory_initialized")
    except Exception:
        log.warning(
            "phase2.long_term_memory_init_failed",
            exc_info=True,
            hint="pgvector extension may not be available",
        )
        app.state.long_term_memory = None

    # Agent registry (in-memory singleton)
    try:
        from src.app.agents.registry import get_agent_registry

        registry = get_agent_registry()
        app.state.agent_registry = registry
        log.info("phase2.agent_registry_initialized", agent_count=len(registry))
    except Exception:
        log.warning("phase2.agent_registry_init_failed", exc_info=True)
        app.state.agent_registry = None

    log.info("phase2.orchestration_modules_initialized")

    # ── Phase 4: Sales Agent Initialization ──────────────────────────────
    # Follows the per-module try/except pattern from Phase 2. If GSuite
    # credentials are not configured, the agent initializes but email/chat
    # services will be None -- handler methods return errors for send tasks.

    try:
        from src.app.agents.sales import SalesAgent, create_sales_registration
        from src.app.agents.sales.qualification import QualificationExtractor
        from src.app.agents.sales.actions import NextActionEngine
        from src.app.agents.sales.escalation import EscalationManager
        from src.app.agents.sales.state_repository import ConversationStateRepository
        from src.app.services.gsuite import GSuiteAuthManager, GmailService, ChatService
        from src.app.core.database import get_tenant_session

        sales_registration = create_sales_registration()

        # GSuite services (may not be configured in dev -- graceful handling)
        gsuite_auth = None
        gmail_service = None
        chat_service = None
        if settings.GOOGLE_SERVICE_ACCOUNT_FILE:
            gsuite_auth = GSuiteAuthManager(
                service_account_file=settings.GOOGLE_SERVICE_ACCOUNT_FILE,
                delegated_user_email=settings.GOOGLE_DELEGATED_USER_EMAIL,
            )
            gmail_service = GmailService(
                auth_manager=gsuite_auth,
                default_user_email=settings.GOOGLE_DELEGATED_USER_EMAIL,
            )
            chat_service = ChatService(auth_manager=gsuite_auth)

        # State repository, qualification, actions, escalation
        state_repo = ConversationStateRepository(session_factory=get_tenant_session)

        # Use a lightweight mock-compatible LLM reference if available
        # In production these come from prior init; in dev they may be None
        llm_service = getattr(app.state, "llm_service", None)
        event_bus = getattr(app.state, "event_bus", None)
        rag_pipeline = getattr(app.state, "rag_pipeline", None)
        conversation_store = getattr(app.state, "conversation_store", None)
        session_manager = getattr(app.state, "session_manager", None)

        qual_extractor = QualificationExtractor(llm_service=llm_service)
        action_engine = NextActionEngine(llm_service=llm_service)
        escalation_mgr = EscalationManager(
            event_bus=event_bus, llm_service=llm_service
        )

        sales_agent = SalesAgent(
            registration=sales_registration,
            llm_service=llm_service,
            gmail_service=gmail_service,
            chat_service=chat_service,
            rag_pipeline=rag_pipeline,
            conversation_store=conversation_store,
            session_manager=session_manager,
            state_repository=state_repo,
            qualification_extractor=qual_extractor,
            action_engine=action_engine,
            escalation_manager=escalation_mgr,
        )

        # Register in agent registry (per 02-05 pattern)
        agent_registry = getattr(app.state, "agent_registry", None)
        if agent_registry is not None:
            agent_registry.register(sales_registration)
            sales_registration._agent_instance = sales_agent
        app.state.sales_agent = sales_agent
        log.info("phase4.sales_agent_initialized")
    except Exception as exc:
        log.warning("phase4.sales_agent_init_failed", error=str(exc))

    # ── Phase 4.1: Agent Learning & Performance Feedback ─────────────
    # All Phase 4.1 init is additive and failure-tolerant. Each component
    # is wrapped in its own try/except so a single failure (e.g., numpy
    # not installed, APScheduler missing) does not prevent startup.

    try:
        from src.app.learning.outcomes import OutcomeTracker
        from src.app.learning.feedback import FeedbackCollector
        from src.app.learning.calibration import CalibrationEngine
        from src.app.learning.coaching import CoachingPatternExtractor
        from src.app.learning.analytics import AnalyticsService
        from src.app.learning.scheduler import setup_learning_scheduler, start_scheduler_background
        from src.app.core.database import get_tenant_session as _get_tenant_session

        outcome_tracker = OutcomeTracker(session_factory=_get_tenant_session)
        feedback_collector = FeedbackCollector(session_factory=_get_tenant_session)
        calibration_engine = CalibrationEngine(session_factory=_get_tenant_session)
        coaching_extractor = CoachingPatternExtractor(session_factory=_get_tenant_session)

        redis_client = getattr(app.state, "redis_client", None) or get_redis_pool()
        analytics_service = AnalyticsService(
            session_factory=_get_tenant_session,
            outcome_tracker=outcome_tracker,
            feedback_collector=feedback_collector,
            calibration_engine=calibration_engine,
            coaching_extractor=coaching_extractor,
            redis_client=redis_client,
        )

        # Store on app.state for API endpoint dependency injection
        app.state.outcome_tracker = outcome_tracker
        app.state.feedback_collector = feedback_collector
        app.state.calibration_engine = calibration_engine
        app.state.coaching_extractor = coaching_extractor
        app.state.analytics_service = analytics_service

        # Start background scheduler tasks
        scheduler_tasks = await setup_learning_scheduler(
            outcome_tracker=outcome_tracker,
            calibration_engine=calibration_engine,
            analytics_service=analytics_service,
        )
        await start_scheduler_background(scheduler_tasks, app.state)

        log.info("phase4_1.learning_system_initialized")
    except Exception as exc:
        log.warning("phase4_1.learning_system_init_failed", error=str(exc))
        # Set all to None for graceful 503 responses from API
        app.state.outcome_tracker = None
        app.state.feedback_collector = None
        app.state.calibration_engine = None
        app.state.coaching_extractor = None
        app.state.analytics_service = None

    # ── Phase 5: Deal Management Module Initialization ──────────────
    try:
        from src.app.deals.repository import DealRepository
        from src.app.deals.detection import OpportunityDetector
        from src.app.deals.political import PoliticalMapper
        from src.app.deals.plans import PlanManager
        from src.app.deals.progression import StageProgressionEngine
        from src.app.deals.hooks import PostConversationHook
        from src.app.deals.crm.postgres import PostgresAdapter
        from src.app.deals.crm.sync import SyncEngine
        from src.app.deals.crm.field_mapping import DEFAULT_FIELD_OWNERSHIP
        from src.app.core.database import get_tenant_session as _get_deal_session

        deal_repository = DealRepository(session_factory=_get_deal_session)
        app.state.deal_repository = deal_repository

        detector = OpportunityDetector()
        political_mapper = PoliticalMapper()
        plan_manager = PlanManager(repository=deal_repository)
        progression_engine = StageProgressionEngine()

        app.state.deal_hook = PostConversationHook(
            detector=detector,
            political_mapper=political_mapper,
            plan_manager=plan_manager,
            progression_engine=progression_engine,
            repository=deal_repository,
        )

        # CRM sync engine (external adapter configured per tenant later)
        app.state.sync_engine = SyncEngine(
            primary=PostgresAdapter(repository=deal_repository, tenant_id=""),
            external=None,  # Configured per-tenant when Notion token is set
            field_ownership=DEFAULT_FIELD_OWNERSHIP,
        )

        log.info("phase5.deal_management_initialized")
    except Exception:
        log.warning("phase5.deal_management_init_failed", exc_info=True)
        app.state.deal_repository = None
        app.state.deal_hook = None
        app.state.sync_engine = None

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    # Clean up Phase 4.1 scheduler tasks
    scheduler_tasks_refs = getattr(app.state, "learning_scheduler_tasks", None)
    if scheduler_tasks_refs:
        for task_ref in scheduler_tasks_refs:
            task_ref.cancel()

    # Close long-term memory pool if it was initialized
    ltm = getattr(app.state, "long_term_memory", None)
    if ltm is not None:
        try:
            await ltm.close()
        except Exception:
            log.warning("phase2.long_term_memory_close_failed", exc_info=True)

    await close_db()
    await close_redis()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Agent Army API",
        version="0.1.0",
        description="Enterprise Sales Organization Platform with Multi-Agent AI Crew",
        lifespan=lifespan,
    )

    # Middleware is added in reverse order (last added = outermost)

    # Tenant middleware (inner -- resolves tenant context from JWT/header)
    redis_client = get_redis_pool()
    app.add_middleware(TenantAuthMiddleware, redis_client=redis_client)

    # CORS middleware
    if settings.CORS_ALLOWED_ORIGINS == "*":
        origins = ["*"]
    else:
        origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Logging middleware (logs every request with timing)
    app.add_middleware(LoggingMiddleware)

    # Metrics middleware (outermost -- records Prometheus metrics for all requests)
    app.add_middleware(MetricsMiddleware)

    # Include v1 API router (health, tenants, auth, etc.)
    app.include_router(v1_router)

    # Prometheus metrics endpoint (infrastructure route, outside v1 router)
    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request) -> Response:
        """Prometheus metrics endpoint."""
        return get_metrics_response()

    return app


# Module-level app for uvicorn
app = create_app()
