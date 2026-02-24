"""Pure Python health scoring algorithm for TAM agent.

Computes a deterministic 0-100 health score from three signal categories:
1. P1/P2 ticket age
2. Open ticket volume
3. Integration heartbeat silence

IMPORTANT: Do NOT use LLM for score computation. The score is a deterministic
numeric calculation. LLM adds latency, cost, and non-determinism for zero benefit.

Exports:
    HealthScorer: Configurable health scoring engine with RAG derivation.
"""

from __future__ import annotations


class HealthScorer:
    """Compute account health score (0-100, higher = healthier) from three signals.

    Scoring formula:
    - Start at 100 (perfect health)
    - P1/P2 ticket age penalty: if oldest ticket > threshold, deduct count * 20
    - Open ticket volume penalty: deduct (excess tickets) * 5
    - Heartbeat silence penalty: -15 if over threshold, -30 if > 2x threshold
    - None heartbeat = not monitored (no penalty)
    - Floor at 0, ceiling at 100

    RAG derivation:
    - Score >= AMBER_THRESHOLD: Green (healthy)
    - Score >= RED_THRESHOLD: Amber (needs attention)
    - Score < RED_THRESHOLD: Red (at risk)

    All thresholds are configurable per-tenant via constructor kwargs.

    Args:
        p1_p2_age_threshold_days: Days before P1/P2 tickets trigger penalty.
        open_ticket_count_threshold: Tickets beyond this count trigger penalty.
        heartbeat_silence_hours: Hours of silence before heartbeat penalty.
        red_threshold: Score below this = Red (at risk).
        amber_threshold: Score below this = Amber (needs attention).
        escalation_threshold: Score below this triggers escalation.
    """

    def __init__(
        self,
        *,
        p1_p2_age_threshold_days: int = 3,
        open_ticket_count_threshold: int = 5,
        heartbeat_silence_hours: int = 72,
        red_threshold: int = 40,
        amber_threshold: int = 70,
        escalation_threshold: int = 40,
    ) -> None:
        self.P1_P2_AGE_THRESHOLD_DAYS = p1_p2_age_threshold_days
        self.OPEN_TICKET_COUNT_THRESHOLD = open_ticket_count_threshold
        self.HEARTBEAT_SILENCE_HOURS = heartbeat_silence_hours
        self.RED_THRESHOLD = red_threshold
        self.AMBER_THRESHOLD = amber_threshold
        self.ESCALATION_THRESHOLD = escalation_threshold

    def compute_score(
        self,
        p1_p2_ticket_count: int,
        oldest_p1_p2_age_days: float,
        total_open_tickets: int,
        hours_since_heartbeat: float | None,
    ) -> tuple[int, str]:
        """Compute health score and RAG status from signal inputs.

        Args:
            p1_p2_ticket_count: Number of open P1/P2 priority tickets.
            oldest_p1_p2_age_days: Age in days of the oldest P1/P2 ticket.
            total_open_tickets: Total number of open tickets across all priorities.
            hours_since_heartbeat: Hours since last integration heartbeat.
                None means heartbeat is not monitored (no penalty applied).

        Returns:
            Tuple of (score, rag_status) where score is 0-100 and
            rag_status is one of "Green", "Amber", "Red".
        """
        score = 100

        # P1/P2 ticket age penalty
        if oldest_p1_p2_age_days > self.P1_P2_AGE_THRESHOLD_DAYS:
            score -= p1_p2_ticket_count * 20

        # Open ticket volume penalty
        excess_tickets = max(0, total_open_tickets - self.OPEN_TICKET_COUNT_THRESHOLD)
        score -= excess_tickets * 5

        # Heartbeat silence penalty
        if hours_since_heartbeat is not None:
            if hours_since_heartbeat > self.HEARTBEAT_SILENCE_HOURS * 2:
                score -= 30
            elif hours_since_heartbeat > self.HEARTBEAT_SILENCE_HOURS:
                score -= 15

        # Floor at 0, ceiling at 100
        score = max(0, min(100, score))

        # Derive RAG status
        if score < self.RED_THRESHOLD:
            rag = "Red"
        elif score < self.AMBER_THRESHOLD:
            rag = "Amber"
        else:
            rag = "Green"

        return score, rag

    def should_escalate(
        self,
        current_score: int,
        current_rag: str,
        previous_rag: str | None,
    ) -> bool:
        """Determine whether an escalation should be triggered.

        Escalation triggers (any one is sufficient):
        1. Current score below ESCALATION_THRESHOLD
        2. RAG worsened to Red from any non-Red state
        3. RAG dropped from Green to Amber (early warning)

        Args:
            current_score: The current health score (0-100).
            current_rag: Current RAG status ("Green", "Amber", "Red").
            previous_rag: Previous RAG status, or None if no prior scan.

        Returns:
            True if escalation should be triggered, False otherwise.
        """
        if current_score < self.ESCALATION_THRESHOLD:
            return True

        if previous_rag is not None and previous_rag != "Red" and current_rag == "Red":
            return True

        if previous_rag == "Green" and current_rag == "Amber":
            return True

        return False


__all__ = ["HealthScorer"]
