"""Learning and feedback module for agent performance tracking.

Provides outcome tracking, feedback collection, confidence calibration,
and performance analytics for the Sales Agent. Builds on Phase 4's
Sales Agent Core to enable continuous learning from interaction outcomes.

Components:
- models: SQLAlchemy models (OutcomeRecordModel, FeedbackEntryModel, CalibrationBinModel)
- schemas: Pydantic schemas for outcomes, feedback, calibration, analytics
- outcomes: OutcomeTracker service for recording and resolving agent action outcomes
"""
