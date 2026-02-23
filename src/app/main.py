"""FastAPI application factory.

Creates the app with tenant middleware, logging middleware, metrics middleware,
CORS, Sentry, lifespan events for database initialization, and the v1 API router.
"""

from __future__ import annotations

import asyncio
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
        from src.app.agents.sales.qbs import QBSQuestionEngine, AccountExpansionDetector

        sales_registration = create_sales_registration()

        # GSuite services (may not be configured in dev -- graceful handling)
        gsuite_auth = None
        gmail_service = None
        chat_service = None
        sa_path = settings.get_service_account_path()
        if sa_path:
            gsuite_auth = GSuiteAuthManager(
                service_account_file=sa_path,
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

        # Phase 4.2: QBS methodology components
        qbs_engine = QBSQuestionEngine(llm_service=llm_service)
        expansion_detector = AccountExpansionDetector(llm_service=llm_service)

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
            qbs_engine=qbs_engine,
            expansion_detector=expansion_detector,
        )

        # Register in agent registry (per 02-05 pattern)
        agent_registry = getattr(app.state, "agent_registry", None)
        if agent_registry is not None:
            agent_registry.register(sales_registration)
            sales_registration._agent_instance = sales_agent
        app.state.sales_agent = sales_agent
        app.state.qbs_engine = qbs_engine
        app.state.expansion_detector = expansion_detector
        log.info("phase4.sales_agent_initialized", qbs_enabled=True)
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

    # ── Phase 10: Solution Architect Agent ────────────────────────────
    # Follows the Sales Agent pattern: instantiate with shared services,
    # register in AgentRegistry. Fail-tolerant -- SA unavailability
    # does not prevent app startup.

    try:
        from src.app.agents.solution_architect import (
            SolutionArchitectAgent,
            create_sa_registration,
        )

        sa_registration = create_sa_registration()

        sa_agent = SolutionArchitectAgent(
            registration=sa_registration,
            llm_service=getattr(app.state, "llm_service", None)
            or locals().get("llm_service"),
            rag_pipeline=getattr(app.state, "rag_pipeline", None)
            or locals().get("rag_pipeline"),
        )

        # Register in agent registry
        agent_registry = getattr(app.state, "agent_registry", None)
        if agent_registry is not None:
            agent_registry.register(sa_registration)
            sa_registration._agent_instance = sa_agent
        app.state.solution_architect = sa_agent
        log.info("phase10.solution_architect_initialized")
    except Exception as exc:
        log.warning("phase10.solution_architect_init_failed", error=str(exc))

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
        _notion_adapter = None
        if settings.NOTION_TOKEN and settings.NOTION_DATABASE_ID:
            try:
                from src.app.deals.crm.notion import NotionAdapter

                _notion_adapter = NotionAdapter(
                    token=settings.NOTION_TOKEN,
                    database_id=settings.NOTION_DATABASE_ID,
                )
                log.info(
                    "phase5.notion_adapter_initialized",
                    database_id=settings.NOTION_DATABASE_ID,
                )
            except Exception:
                log.warning("phase5.notion_adapter_init_failed", exc_info=True)

        app.state.sync_engine = SyncEngine(
            primary=PostgresAdapter(repository=deal_repository, tenant_id=""),
            external=_notion_adapter,
            field_ownership=DEFAULT_FIELD_OWNERSHIP,
        )

        log.info("phase5.deal_management_initialized")
    except Exception:
        log.warning("phase5.deal_management_init_failed", exc_info=True)
        app.state.deal_repository = None
        app.state.deal_hook = None
        app.state.sync_engine = None

    # ── Phase 6: Meeting Capabilities ──────────────────────────────
    try:
        from src.app.meetings.repository import MeetingRepository
        from src.app.meetings.calendar.monitor import CalendarMonitor
        from src.app.meetings.calendar.briefing import BriefingGenerator
        from src.app.meetings.bot.recall_client import RecallClient
        from src.app.meetings.bot.manager import BotManager
        from src.app.meetings.minutes.generator import MinutesGenerator
        from src.app.meetings.minutes.distributor import MinutesDistributor
        from src.app.core.database import get_tenant_session as _get_meeting_session

        meeting_repo = MeetingRepository(session_factory=_get_meeting_session)
        app.state.meeting_repository = meeting_repo

        # Calendar service (reconstruct GSuite auth if credentials configured)
        calendar_service = None
        try:
            _sa_path_cal = settings.get_service_account_path()
            if _sa_path_cal:
                from src.app.services.gsuite import GSuiteAuthManager as _GSuiteAuth
                from src.app.services.gsuite.calendar import GoogleCalendarService

                _gsuite_auth = _GSuiteAuth(
                    service_account_file=_sa_path_cal,
                    delegated_user_email=settings.GOOGLE_DELEGATED_USER_EMAIL,
                )
                calendar_service = GoogleCalendarService(auth_manager=_gsuite_auth)
        except Exception:
            log.warning("phase6.calendar_service_init_failed", exc_info=True)

        # Briefing generator
        llm_service = getattr(app.state, "llm_service", None)
        deal_repo = getattr(app.state, "deal_repository", None)
        briefing_gen = BriefingGenerator(
            repository=meeting_repo,
            llm_service=llm_service,
            deal_repository=deal_repo,
        )
        app.state.briefing_generator = briefing_gen

        # TTS client for entrance greeting (best-effort)
        _tts_client_for_bot = None
        if settings.ELEVENLABS_API_KEY:
            try:
                from src.app.meetings.realtime.tts import ElevenLabsTTS as _ElevenLabsTTS
                _tts_client_for_bot = _ElevenLabsTTS(
                    api_key=settings.ELEVENLABS_API_KEY,
                    voice_id=settings.ELEVENLABS_VOICE_ID,
                )
            except Exception:
                log.warning("phase6.tts_client_init_failed", exc_info=True)

        # Recall.ai bot management
        recall_client = None
        bot_manager = None
        if settings.RECALL_AI_API_KEY:
            recall_client = RecallClient(
                api_key=settings.RECALL_AI_API_KEY,
                region=settings.RECALL_AI_REGION,
            )
            bot_manager = BotManager(
                recall_client=recall_client,
                repository=meeting_repo,
                settings=settings,
                tts_client=_tts_client_for_bot,
                deepgram_api_key=settings.DEEPGRAM_API_KEY,
                elevenlabs_api_key=settings.ELEVENLABS_API_KEY,
                elevenlabs_voice_id=settings.ELEVENLABS_VOICE_ID,
                heygen_api_key=settings.HEYGEN_API_KEY,
                heygen_avatar_id=settings.HEYGEN_AVATAR_ID,
                llm_service=llm_service,
                app_state=app.state,
            )
        app.state.bot_manager = bot_manager

        # Real-time pipeline API keys (stored for per-meeting pipeline creation)
        app.state.deepgram_api_key = settings.DEEPGRAM_API_KEY
        app.state.elevenlabs_api_key = settings.ELEVENLABS_API_KEY
        app.state.elevenlabs_voice_id = settings.ELEVENLABS_VOICE_ID
        app.state.heygen_api_key = settings.HEYGEN_API_KEY
        app.state.heygen_avatar_id = settings.HEYGEN_AVATAR_ID

        # Minutes pipeline
        minutes_gen = MinutesGenerator(repository=meeting_repo, llm_service=llm_service)
        # Gmail service: reconstruct or get from app.state
        _gmail_svc = None
        try:
            _sa_path_gmail = settings.get_service_account_path()
            if _sa_path_gmail:
                from src.app.services.gsuite import GmailService as _GmailSvc
                from src.app.services.gsuite import GSuiteAuthManager as _GSuiteAuth2

                _gsuite_auth2 = _GSuiteAuth2(
                    service_account_file=_sa_path_gmail,
                    delegated_user_email=settings.GOOGLE_DELEGATED_USER_EMAIL,
                )
                _gmail_svc = _GmailSvc(
                    auth_manager=_gsuite_auth2,
                    default_user_email=settings.GOOGLE_DELEGATED_USER_EMAIL,
                )
        except Exception:
            log.warning("phase6.gmail_service_init_failed", exc_info=True)

        minutes_dist = MinutesDistributor(
            repository=meeting_repo,
            gmail_service=_gmail_svc,
        )
        app.state.minutes_generator = minutes_gen
        app.state.minutes_distributor = minutes_dist

        # Calendar monitor with poll loop
        calendar_monitor = None
        if calendar_service:
            calendar_monitor = CalendarMonitor(
                calendar_service=calendar_service,
                repository=meeting_repo,
                briefing_generator=briefing_gen,
                bot_manager=bot_manager,
            )
            app.state.calendar_monitor = calendar_monitor
            log.info("phase6.calendar_monitor_ready")
        else:
            app.state.calendar_monitor = None

        # Start calendar monitoring background task
        if calendar_monitor and settings.GOOGLE_DELEGATED_USER_EMAIL:
            try:
                _monitor_task = asyncio.create_task(
                    calendar_monitor.run_poll_loop(
                        agent_email=settings.GOOGLE_DELEGATED_USER_EMAIL,
                        tenant_id="system",
                    ),
                    name="calendar_monitor_poll",
                )
                app.state.calendar_monitor_task = _monitor_task
                log.info(
                    "phase6.calendar_monitor_started",
                    agent_email=settings.GOOGLE_DELEGATED_USER_EMAIL,
                    poll_interval_seconds=900,
                )
            except Exception:
                log.warning("phase6.calendar_monitor_start_failed", exc_info=True)
                app.state.calendar_monitor_task = None
        else:
            app.state.calendar_monitor_task = None

        log.info("phase6.meeting_capabilities_initialized")
    except Exception as exc:
        log.warning("phase6.meeting_capabilities_init_failed", error=str(exc))
        app.state.meeting_repository = None
        app.state.briefing_generator = None
        app.state.bot_manager = None
        app.state.minutes_generator = None
        app.state.minutes_distributor = None
        app.state.calendar_monitor = None

    # ── Phase 7: Intelligence & Autonomy ──────────────────────────────
    try:
        from src.app.intelligence.repository import IntelligenceRepository
        from src.app.intelligence.consolidation.entity_linker import EntityLinker
        from src.app.intelligence.consolidation.summarizer import ContextSummarizer
        from src.app.intelligence.consolidation.customer_view import CustomerViewService
        from src.app.intelligence.patterns.engine import create_default_engine
        from src.app.intelligence.patterns.insights import InsightGenerator
        from src.app.intelligence.autonomy.guardrails import GuardrailChecker
        from src.app.intelligence.autonomy.goals import GoalTracker
        from src.app.intelligence.autonomy.engine import AutonomyEngine
        from src.app.intelligence.autonomy.scheduler import (
            setup_intelligence_scheduler,
            start_intelligence_scheduler_background,
        )
        from src.app.intelligence.persona.geographic import GeographicAdapter
        from src.app.intelligence.persona.cloning import AgentCloneManager
        from src.app.intelligence.persona.persona_builder import PersonaBuilder
        from src.app.core.database import get_tenant_session as _get_intel_session

        intel_repo = IntelligenceRepository(session_factory=_get_intel_session)
        app.state.intelligence_repository = intel_repo

        # Consolidation
        entity_linker = EntityLinker()
        summarizer = ContextSummarizer(llm_service=llm_service)
        customer_view_service = CustomerViewService(
            conversation_store=getattr(app.state, "conversation_store", None),
            state_repository=(
                getattr(app.state, "sales_agent", None)
                and getattr(app.state.sales_agent, "_state_repository", None)
            ),
            deal_repository=getattr(app.state, "deal_repository", None),
            meeting_repository=getattr(app.state, "meeting_repository", None),
            summarizer=summarizer,
            entity_linker=entity_linker,
        )
        app.state.customer_view_service = customer_view_service

        # Patterns
        pattern_engine = create_default_engine(llm_service=llm_service)
        insight_generator = InsightGenerator(
            repository=intel_repo,
            event_bus=getattr(app.state, "event_bus", None),
        )
        app.state.pattern_engine = pattern_engine
        app.state.insight_generator = insight_generator

        # Autonomy
        guardrail_checker = GuardrailChecker()
        goal_tracker = GoalTracker(repository=intel_repo)
        autonomy_engine = AutonomyEngine(
            guardrail_checker=guardrail_checker,
            goal_tracker=goal_tracker,
            pattern_engine=pattern_engine,
            repository=intel_repo,
            llm_service=llm_service,
        )
        app.state.autonomy_engine = autonomy_engine
        app.state.goal_tracker = goal_tracker
        app.state.guardrail_checker = guardrail_checker

        # Persona & Cloning
        geographic_adapter = GeographicAdapter()
        clone_manager = AgentCloneManager(repository=intel_repo, llm_service=llm_service)
        persona_builder = PersonaBuilder(llm_service=llm_service, geographic_adapter=geographic_adapter)
        app.state.geographic_adapter = geographic_adapter
        app.state.clone_manager = clone_manager
        app.state.persona_builder = persona_builder

        # Intelligence scheduler (background tasks)
        intel_tasks = await setup_intelligence_scheduler(
            pattern_engine=pattern_engine,
            autonomy_engine=autonomy_engine,
            goal_tracker=goal_tracker,
            insight_generator=insight_generator,
            customer_view_service=customer_view_service,
        )
        await start_intelligence_scheduler_background(intel_tasks, app.state)

        log.info("phase7.intelligence_initialized")
    except Exception as exc:
        log.warning("phase7.intelligence_init_failed", error=str(exc))
        # Set all to None for graceful 503 responses
        app.state.intelligence_repository = None
        app.state.customer_view_service = None
        app.state.pattern_engine = None
        app.state.insight_generator = None
        app.state.autonomy_engine = None
        app.state.goal_tracker = None
        app.state.guardrail_checker = None
        app.state.geographic_adapter = None
        app.state.clone_manager = None
        app.state.persona_builder = None

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────
    # Clean up Phase 4.1 scheduler tasks
    scheduler_tasks_refs = getattr(app.state, "learning_scheduler_tasks", None)
    if scheduler_tasks_refs:
        for task_ref in scheduler_tasks_refs:
            task_ref.cancel()

    # Clean up Phase 7 intelligence scheduler tasks
    intel_scheduler_refs = getattr(app.state, "intelligence_scheduler_tasks", None)
    if intel_scheduler_refs:
        for task_ref in intel_scheduler_refs:
            task_ref.cancel()

    # Clean up Phase 6 calendar monitor task
    calendar_monitor_task = getattr(app.state, "calendar_monitor_task", None)
    if calendar_monitor_task and not calendar_monitor_task.done():
        _cm = getattr(app.state, "calendar_monitor", None)
        if _cm is not None:
            _cm.stop()
        calendar_monitor_task.cancel()
        try:
            await calendar_monitor_task
        except asyncio.CancelledError:
            pass
        log.info("phase6.calendar_monitor_stopped")

    # Clean up active real-time pipelines
    bot_mgr = getattr(app.state, "bot_manager", None)
    if bot_mgr is not None:
        for mid, pipeline in getattr(bot_mgr, "_active_pipelines", {}).items():
            try:
                if hasattr(pipeline, "shutdown"):
                    await pipeline.shutdown()
            except Exception:
                log.warning("phase6.pipeline_cleanup_error", meeting_id=mid, exc_info=True)

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
