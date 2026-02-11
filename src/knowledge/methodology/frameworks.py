"""Pydantic models for MEDDIC, BANT, and SPIN sales methodology frameworks.

Provides both structured programmatic access (MethodologyLibrary) and the
data definitions for three industry-standard sales methodologies. Each
framework contains steps with key questions, examples showing good vs bad
approaches, and practical tips.

These models are designed to be used directly by agents for structured
responses AND to feed markdown documents for semantic search ingestion.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Models ─────────────────────────────────────────────────────────────────


class MethodologyExample(BaseModel):
    """A concrete example illustrating correct vs incorrect methodology usage.

    Attributes:
        scenario: The sales situation being addressed.
        good_example: An effective application of the methodology step.
        bad_example: A common mistake or poor application.
        explanation: Why the good example is more effective.
    """

    scenario: str
    good_example: str
    bad_example: str
    explanation: str


class MethodologyStep(BaseModel):
    """A single step within a sales methodology framework.

    Each step represents one element of the methodology's acronym (e.g., 'M'
    in MEDDIC = Metrics). Steps contain practical questions reps should ask,
    examples of good vs bad execution, and tips for real-world application.

    Attributes:
        name: Full name of the step (e.g., "Metrics").
        abbreviation: Letter or short code (e.g., "M").
        description: What this step covers and why it matters.
        purpose: The strategic goal of this step in the sales process.
        key_questions: Specific questions a rep should ask (5-8 per step).
        examples: Concrete good-vs-bad usage examples.
        sales_stage: Which pipeline stage this step typically applies to.
        tips: Practical guidance for executing this step well.
    """

    name: str
    abbreviation: str
    description: str
    purpose: str
    key_questions: list[str] = Field(default_factory=list)
    examples: list[MethodologyExample] = Field(default_factory=list)
    sales_stage: str = "discovery"
    tips: list[str] = Field(default_factory=list)


class MethodologyFramework(BaseModel):
    """A complete sales methodology framework (e.g., MEDDIC, BANT, SPIN).

    Attributes:
        name: Short framework name (e.g., "MEDDIC").
        full_name: Expanded acronym or subtitle.
        description: Overview of the methodology and its origins.
        when_to_use: Guidance on when this framework is most effective.
        steps: The ordered list of methodology steps.
        summary_checklist: Quick-reference checklist items for deal review.
    """

    name: str
    full_name: str
    description: str
    when_to_use: str
    steps: list[MethodologyStep] = Field(default_factory=list)
    summary_checklist: list[str] = Field(default_factory=list)


# ── Library ────────────────────────────────────────────────────────────────


class MethodologyLibrary:
    """Central access point for all sales methodology frameworks.

    Pre-populated with MEDDIC, BANT, and SPIN on instantiation. Provides
    structured lookup by framework name, step name, and sales stage.

    Usage::

        lib = MethodologyLibrary()
        meddic = lib.get_framework("MEDDIC")
        metrics = lib.get_step("MEDDIC", "Metrics")
        discovery_qs = lib.get_questions_for_stage("discovery")
    """

    def __init__(self) -> None:
        self.frameworks: dict[str, MethodologyFramework] = {}
        self._populate_meddic()
        self._populate_bant()
        self._populate_spin()

    def get_framework(self, name: str) -> MethodologyFramework:
        """Retrieve a framework by name (case-insensitive).

        Args:
            name: Framework name (e.g., "MEDDIC", "meddic").

        Returns:
            The matching MethodologyFramework.

        Raises:
            KeyError: If the framework name is not found.
        """
        key = name.upper()
        if key not in self.frameworks:
            raise KeyError(f"Unknown methodology: {name}. Available: {list(self.frameworks.keys())}")
        return self.frameworks[key]

    def get_step(self, framework: str, step: str) -> MethodologyStep:
        """Retrieve a specific step within a framework.

        Args:
            framework: Framework name (e.g., "MEDDIC").
            step: Step name (e.g., "Metrics") or abbreviation (e.g., "M").

        Returns:
            The matching MethodologyStep.

        Raises:
            KeyError: If the framework or step is not found.
        """
        fw = self.get_framework(framework)
        step_lower = step.lower()
        for s in fw.steps:
            if s.name.lower() == step_lower or s.abbreviation.lower() == step_lower:
                return s
        available = [f"{s.abbreviation} ({s.name})" for s in fw.steps]
        raise KeyError(f"Unknown step '{step}' in {framework}. Available: {available}")

    def get_questions_for_stage(self, stage: str) -> list[dict]:
        """Get all methodology questions relevant to a specific sales stage.

        Returns questions from all frameworks whose steps apply to the given
        stage, organized by framework and step.

        Args:
            stage: Sales stage (e.g., "discovery", "negotiation").

        Returns:
            List of dicts with keys: framework, step, questions.
        """
        results: list[dict] = []
        stage_lower = stage.lower()
        for fw in self.frameworks.values():
            for step in fw.steps:
                if step.sales_stage.lower() == stage_lower:
                    results.append(
                        {
                            "framework": fw.name,
                            "step": step.name,
                            "questions": step.key_questions,
                        }
                    )
        return results

    # ── Framework Definitions ──────────────────────────────────────────────

    def _populate_meddic(self) -> None:
        """Populate the MEDDIC framework with rich content."""
        self.frameworks["MEDDIC"] = MethodologyFramework(
            name="MEDDIC",
            full_name="Metrics, Economic Buyer, Decision Criteria, Decision Process, Identify Pain, Champion",
            description=(
                "MEDDIC is a B2B sales qualification methodology developed at PTC in the 1990s. "
                "It provides a rigorous framework for understanding complex enterprise deals by "
                "mapping the customer's buying process, identifying key stakeholders, and quantifying "
                "the business impact. MEDDIC is the gold standard for enterprise sales qualification."
            ),
            when_to_use=(
                "Use MEDDIC for complex enterprise deals with multiple stakeholders, long sales "
                "cycles (3-12+ months), deal values above $50K, and formal procurement processes. "
                "MEDDIC excels when you need to deeply understand the customer's decision-making "
                "structure and build internal champions."
            ),
            steps=[
                MethodologyStep(
                    name="Metrics",
                    abbreviation="M",
                    description=(
                        "Quantifiable measures of the business impact your solution delivers. "
                        "Metrics prove ROI and create urgency by attaching numbers to the pain."
                    ),
                    purpose=(
                        "Without metrics, your deal lacks urgency and executive sponsorship. "
                        "Metrics translate technical features into business outcomes that justify "
                        "budget allocation and accelerate procurement."
                    ),
                    key_questions=[
                        "What KPIs are you currently measured on?",
                        "How would you quantify the cost of the current problem?",
                        "What improvement targets has leadership set for this initiative?",
                        "If we could solve this, what would the revenue impact be in the first year?",
                        "How are you measuring success for this project today?",
                        "What is the cost per hour/day when this problem occurs?",
                        "What efficiency gains would justify the investment to your CFO?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Selling billing automation to a telecom company",
                            good_example=(
                                "'Based on your 2M subscriber base and $3.50 average cost per billing "
                                "error, automating dispute resolution could save $2.1M annually. "
                                "What does your finance team see as the breakeven timeline?'"
                            ),
                            bad_example=(
                                "'Our billing platform is really fast and reduces errors.'"
                            ),
                            explanation=(
                                "The good example ties the solution to specific, quantified business "
                                "impact using the customer's own numbers. The bad example is generic "
                                "and gives no basis for ROI calculation."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Always use the customer's own numbers, not industry averages",
                        "Build a simple ROI model early and refine it with the champion",
                        "Metrics should map to the Economic Buyer's compensation objectives",
                        "If the customer cannot quantify the pain, the deal is not real",
                    ],
                ),
                MethodologyStep(
                    name="Economic Buyer",
                    abbreviation="E",
                    description=(
                        "The person with final authority to approve budget and sign the purchase "
                        "order. Not necessarily the most senior person, but the one who controls "
                        "the specific budget line item."
                    ),
                    purpose=(
                        "Deals without Economic Buyer access stall or die. Identifying and "
                        "building a relationship with the EB ensures your deal has executive "
                        "sponsorship and budget authority."
                    ),
                    key_questions=[
                        "Who has the final sign-off authority for this purchase?",
                        "Is there a budget already allocated for this initiative?",
                        "Who controls the budget line item this would fall under?",
                        "What is the approval process once your team makes a recommendation?",
                        "Has this person approved similar purchases in the past?",
                        "Who can kill this deal?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Identifying the Economic Buyer in an enterprise deal",
                            good_example=(
                                "'Who signs the purchase order for technology investments in your "
                                "revenue operations group? I want to make sure we address their "
                                "priorities in our proposal.'"
                            ),
                            bad_example="'Who is your boss? Can I talk to them?'",
                            explanation=(
                                "The good example asks about process authority (who signs) and shows "
                                "respect for the contact's role. The bad example is confrontational "
                                "and implies the contact lacks authority."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "The EB is defined by budget authority, not org chart position",
                        "Ask 'Who can say no?' to identify veto power holders",
                        "Get your Champion to arrange EB access -- do not go around them",
                        "Prepare a concise executive briefing focused on business outcomes, not features",
                    ],
                ),
                MethodologyStep(
                    name="Decision Criteria",
                    abbreviation="D",
                    description=(
                        "The formal and informal criteria the customer uses to evaluate and "
                        "compare vendors. Includes technical requirements, business requirements, "
                        "and cultural fit factors."
                    ),
                    purpose=(
                        "Understanding decision criteria lets you shape the evaluation in your "
                        "favor. If you discover the criteria late, a competitor has already set "
                        "them. If you help define them, you win."
                    ),
                    key_questions=[
                        "What criteria will you use to evaluate potential solutions?",
                        "How are you weighting technical vs business vs cost factors?",
                        "Are there any must-have requirements that would eliminate a vendor?",
                        "Has your team already created an RFP or evaluation scorecard?",
                        "What criteria did you use in your last technology purchase?",
                        "Who defines the evaluation criteria -- IT, business, procurement?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Understanding decision criteria for a charging platform",
                            good_example=(
                                "'When you evaluated your current billing system three years ago, "
                                "what were the top three criteria? And how have your priorities "
                                "shifted since then with the move to usage-based pricing?'"
                            ),
                            bad_example=(
                                "'Here are the 47 features our platform supports. Which ones "
                                "matter to you?'"
                            ),
                            explanation=(
                                "The good example uncovers evolving criteria tied to business "
                                "change. The bad example dumps features and puts the burden on "
                                "the customer to sort through them."
                            ),
                        ),
                    ],
                    sales_stage="evaluation",
                    tips=[
                        "Decision criteria are rarely static -- revisit them as the evaluation progresses",
                        "Help your Champion add criteria where you are strongest",
                        "Technical criteria are table stakes; business outcome criteria differentiate",
                        "If procurement adds new criteria late, a competitor is influencing them",
                    ],
                ),
                MethodologyStep(
                    name="Decision Process",
                    abbreviation="D",
                    description=(
                        "The sequence of steps, approvals, and events the customer follows to "
                        "make a purchasing decision. Includes timeline, stakeholder sign-offs, "
                        "legal review, and procurement steps."
                    ),
                    purpose=(
                        "Mapping the decision process prevents surprises and lets you create a "
                        "mutual action plan. Deals slip when you do not know about legal review, "
                        "security audit, or board approval requirements."
                    ),
                    key_questions=[
                        "Can you walk me through the steps from recommendation to signed contract?",
                        "What approvals are required beyond the project team's recommendation?",
                        "Is there a legal or security review required for new vendors?",
                        "What is your target go-live date, and what drives that timeline?",
                        "Have you been through a procurement process like this recently?",
                        "Are there any budget cycle deadlines we should be aware of?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Mapping the buying process for an enterprise deal",
                            good_example=(
                                "'Let me make sure I understand the process: your team evaluates "
                                "and recommends, then VP Engineering approves, legal reviews the "
                                "MSA, and procurement negotiates final terms. Is there anything "
                                "I am missing? What is the typical timeline for each step?'"
                            ),
                            bad_example="'When can we close this deal?'",
                            explanation=(
                                "The good example demonstrates understanding and invites correction. "
                                "The bad example shows no understanding of the customer's internal "
                                "process and comes across as pushy."
                            ),
                        ),
                    ],
                    sales_stage="evaluation",
                    tips=[
                        "Create a mutual action plan with your Champion mapping every step",
                        "Build in buffer time for legal and security reviews",
                        "Ask about procurement holidays and budget freeze periods",
                        "If the process is unclear, the deal is not real",
                    ],
                ),
                MethodologyStep(
                    name="Identify Pain",
                    abbreviation="I",
                    description=(
                        "The specific business pain the customer is experiencing that creates "
                        "urgency to act. Pain must be tied to business impact (revenue loss, "
                        "cost, risk, competitive disadvantage) rather than technical annoyance."
                    ),
                    purpose=(
                        "Pain creates urgency. Without identified pain linked to business "
                        "impact, there is no compelling reason to buy now. Strong pain "
                        "identification is the foundation of every closed deal."
                    ),
                    key_questions=[
                        "What is the biggest challenge you face with your current approach?",
                        "How is this problem affecting your team's productivity?",
                        "What happens if you do nothing and this problem persists for another year?",
                        "How does this issue impact your customers' experience?",
                        "What have you tried so far to solve this?",
                        "Is this problem getting worse, staying the same, or improving on its own?",
                        "Who else in the organization is affected by this problem?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Identifying pain in a billing transformation deal",
                            good_example=(
                                "'You mentioned billing errors are causing 15% of your support "
                                "tickets. Help me understand: what is the downstream impact? "
                                "Are you seeing churn from customers who receive incorrect invoices?'"
                            ),
                            bad_example=(
                                "'Billing errors are a common problem. Our platform reduces "
                                "errors by 95%.'"
                            ),
                            explanation=(
                                "The good example deepens the pain by exploring downstream business "
                                "impact. The bad example skips pain exploration and jumps to "
                                "solution pitching."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Pain must be personal -- understand how it affects the individual, not just the org",
                        "Use 'what happens if you do nothing?' to test urgency",
                        "Layer pain: technical pain -> business pain -> personal pain",
                        "If there is no pain, there is no deal. Move on.",
                    ],
                ),
                MethodologyStep(
                    name="Champion",
                    abbreviation="C",
                    description=(
                        "An internal advocate who has power, influence, and a personal stake "
                        "in your success. The Champion sells internally when you are not in "
                        "the room and navigates organizational politics on your behalf."
                    ),
                    purpose=(
                        "A true Champion is the single most important factor in winning "
                        "enterprise deals. They provide inside information, coach you on "
                        "objections, and advocate for your solution to the Economic Buyer."
                    ),
                    key_questions=[
                        "Who on your team is most affected by this problem day-to-day?",
                        "Who stands to benefit most from solving this?",
                        "Is there someone who has championed similar initiatives successfully?",
                        "Who has the credibility to make a recommendation to the decision-maker?",
                        "What would a successful outcome mean for your career and team?",
                        "Can you help me understand how to position this for your leadership?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Testing whether your contact is a true Champion",
                            good_example=(
                                "'If I prepare an executive briefing document, would you be "
                                "comfortable presenting it to your VP with your recommendation? "
                                "What concerns would they raise that we should address proactively?'"
                            ),
                            bad_example=(
                                "'Can you set up a meeting with your VP for me?'"
                            ),
                            explanation=(
                                "The good example tests willingness to advocate and coaches them "
                                "for the internal conversation. The bad example just asks for access "
                                "without equipping the Champion or testing their commitment."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "A Champion has three qualities: power, influence, and personal motivation",
                        "Test your Champion: ask them to do something (share info, arrange meeting)",
                        "Coach your Champion on how to sell internally -- give them the talking points",
                        "If your Champion leaves the company, your deal is at risk. Always build multiple relationships.",
                    ],
                ),
            ],
            summary_checklist=[
                "Metrics: Can the customer quantify the business impact (revenue/cost)?",
                "Economic Buyer: Have you identified and accessed the budget holder?",
                "Decision Criteria: Do you know the formal evaluation criteria and can you influence them?",
                "Decision Process: Have you mapped every step from evaluation to signed contract?",
                "Identify Pain: Is there a compelling, urgent business pain driving the purchase?",
                "Champion: Do you have an internal advocate who will sell for you when you are not in the room?",
            ],
        )

    def _populate_bant(self) -> None:
        """Populate the BANT framework with rich content."""
        self.frameworks["BANT"] = MethodologyFramework(
            name="BANT",
            full_name="Budget, Authority, Need, Timeline",
            description=(
                "BANT is a classic sales qualification framework originally developed at IBM. "
                "It provides a quick, structured approach to determine whether a prospect is "
                "worth pursuing by evaluating four key dimensions. While simpler than MEDDIC, "
                "BANT remains highly effective for transactional and mid-market sales cycles."
            ),
            when_to_use=(
                "Use BANT for faster, simpler deals with shorter sales cycles (1-3 months), "
                "deal values under $50K, fewer stakeholders, and less formal procurement. "
                "BANT is ideal for initial qualification and SDR/BDR prospecting. For complex "
                "enterprise deals, transition to MEDDIC after initial BANT qualification."
            ),
            steps=[
                MethodologyStep(
                    name="Budget",
                    abbreviation="B",
                    description=(
                        "Determine whether the prospect has the financial resources allocated "
                        "or allocable for this purchase. Modern BANT treats budget as 'is this "
                        "a funded initiative?' rather than 'do you have money?'"
                    ),
                    purpose=(
                        "Budget qualification prevents spending time on prospects who cannot "
                        "buy. Modern budget qualification focuses on whether the problem is "
                        "important enough to fund, not whether a specific line item exists."
                    ),
                    key_questions=[
                        "Is this initiative part of a funded project or business priority?",
                        "How does your organization typically fund new technology investments?",
                        "What budget range are you working within for this type of solution?",
                        "Has budget been formally allocated, or would it need to be requested?",
                        "What is the cost of the current solution or manual process?",
                        "Would this come from operational budget or a capital expenditure?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Qualifying budget for a mid-market SaaS deal",
                            good_example=(
                                "'Is reducing billing errors a funded priority for this quarter, "
                                "or would you need to build a business case to request budget? "
                                "I ask because timing the proposal matters.'"
                            ),
                            bad_example="'What is your budget?'",
                            explanation=(
                                "The good example determines funding status without putting the "
                                "prospect on the spot. The bad example is blunt and often gets "
                                "a deflective answer."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Budget is less about 'do you have money' and more about 'is this a funded initiative'",
                        "If no budget exists, help the champion build a business case to secure it",
                        "Ask about the cost of the status quo to frame your solution as a savings, not an expense",
                        "In early-stage startups, budget flexibility is higher -- focus on ROI payback period",
                    ],
                ),
                MethodologyStep(
                    name="Authority",
                    abbreviation="A",
                    description=(
                        "Identify who has the decision-making authority for this purchase. "
                        "Authority means the ability to sign off on budget, approve vendors, "
                        "and execute contracts."
                    ),
                    purpose=(
                        "Selling to someone without authority wastes cycles. Identify the "
                        "decision-maker early and ensure your message reaches them, either "
                        "directly or through your internal coach."
                    ),
                    key_questions=[
                        "Who else needs to be involved in this decision?",
                        "What is the approval process for a purchase of this size?",
                        "Have you made a similar purchasing decision before?",
                        "Who would sign the contract if we move forward?",
                        "Is there a committee or review board that evaluates new vendors?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Determining authority in a growing company",
                            good_example=(
                                "'For technology purchases in this range, what does the approval "
                                "chain look like at your company? I want to make sure we provide "
                                "the right materials for each stakeholder.'"
                            ),
                            bad_example="'Are you the decision-maker?'",
                            explanation=(
                                "The good example asks about the process (not the person) and "
                                "offers to help. The bad example can be insulting and usually "
                                "gets a defensive 'yes' even when the answer is no."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Never ask 'Are you the decision-maker?' -- it is confrontational",
                        "In consensus-driven organizations, authority is shared -- map all stakeholders",
                        "Authority for tech purchases often sits with finance, not the end user",
                        "If your contact says 'I just need to run it by my team,' there are more decision-makers",
                    ],
                ),
                MethodologyStep(
                    name="Need",
                    abbreviation="N",
                    description=(
                        "Understand the specific business need or problem the prospect is "
                        "trying to solve. Need goes beyond 'nice to have' to 'must solve.'"
                    ),
                    purpose=(
                        "A validated need means the prospect has a real problem worth solving "
                        "now. Without genuine need, deals stall in 'evaluation mode' indefinitely."
                    ),
                    key_questions=[
                        "What specific problem are you trying to solve?",
                        "How is this problem impacting your business today?",
                        "What triggered you to look for a solution now?",
                        "On a scale of 1-10, how urgent is solving this?",
                        "What happens if this problem is not addressed in the next 6 months?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Qualifying need for a charging platform",
                            good_example=(
                                "'You mentioned you are launching a usage-based pricing model "
                                "next quarter. What happens to the launch timeline if the "
                                "charging infrastructure is not in place? What is the revenue "
                                "impact of a delayed launch?'"
                            ),
                            bad_example="'Do you need a charging platform?'",
                            explanation=(
                                "The good example ties need to a business deadline with "
                                "consequences. The bad example gets a yes/no answer with "
                                "no urgency context."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "A need triggered by an event (new exec, competitive threat, regulatory change) is stronger than a wish list",
                        "Ask 'What triggered you to look for a solution now?' to understand urgency",
                        "Differentiate between a need (must solve) and a want (nice to solve)",
                        "If the prospect cannot articulate the business impact, the need may not be strong enough",
                    ],
                ),
                MethodologyStep(
                    name="Timeline",
                    abbreviation="T",
                    description=(
                        "Establish when the prospect needs the solution implemented and what "
                        "events or deadlines drive that timeline."
                    ),
                    purpose=(
                        "Timeline validates urgency and helps forecast accurately. A prospect "
                        "with no timeline has no urgency, and the deal will slip."
                    ),
                    key_questions=[
                        "When do you need this solution in place?",
                        "What is driving that timeline?",
                        "Are there any external deadlines (regulatory, contractual, seasonal)?",
                        "What is the consequence of missing that deadline?",
                        "How long did your last technology implementation take?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Qualifying timeline for a billing migration",
                            good_example=(
                                "'You mentioned your current vendor contract expires in June. "
                                "Working backward from a June go-live, we would need to start "
                                "implementation by March. Does that timeline work with your "
                                "team's availability?'"
                            ),
                            bad_example="'When do you want to get started?'",
                            explanation=(
                                "The good example anchors to a real deadline and works backward "
                                "to create urgency. The bad example has no anchor and gets a "
                                "vague response."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Timeline should be anchored to a business event, not an arbitrary date",
                        "Work backward from go-live to create a mutual action plan",
                        "If the prospect says 'no rush,' the deal will likely not close this quarter",
                        "Regulatory deadlines and contract expirations are the strongest timeline drivers",
                    ],
                ),
            ],
            summary_checklist=[
                "Budget: Is this a funded initiative with allocated or allocable budget?",
                "Authority: Do you know who signs the contract and who influences the decision?",
                "Need: Is there a specific, quantified business problem driving this purchase?",
                "Timeline: Is there a real deadline or event creating urgency to buy now?",
            ],
        )

    def _populate_spin(self) -> None:
        """Populate the SPIN Selling framework with rich content."""
        self.frameworks["SPIN"] = MethodologyFramework(
            name="SPIN",
            full_name="Situation, Problem, Implication, Need-Payoff",
            description=(
                "SPIN Selling was developed by Neil Rackham based on research analyzing over "
                "35,000 sales calls. It is a questioning methodology that guides reps through "
                "a progressive conversation: from understanding the current situation, to "
                "uncovering problems, exploring implications of those problems, and finally "
                "establishing the value of solving them."
            ),
            when_to_use=(
                "Use SPIN in early-stage conversations, particularly discovery calls and "
                "initial meetings. SPIN is most effective when you need to help the prospect "
                "realize the full impact of their problem before presenting a solution. It "
                "integrates well with MEDDIC: use SPIN for discovery questioning, then MEDDIC "
                "for qualification tracking."
            ),
            steps=[
                MethodologyStep(
                    name="Situation",
                    abbreviation="S",
                    description=(
                        "Questions that gather facts about the customer's current state, "
                        "environment, processes, and tools. These establish context for the "
                        "rest of the conversation."
                    ),
                    purpose=(
                        "Situation questions build your understanding of the customer's world. "
                        "Keep these minimal -- experienced reps research before the call and "
                        "use situation questions to confirm and fill gaps, not to interrogate."
                    ),
                    key_questions=[
                        "How does your current billing/charging process work end-to-end?",
                        "What systems are you using today for revenue management?",
                        "How many customers/transactions do you process monthly?",
                        "Who is involved in managing the current system?",
                        "How long have you been using your current approach?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Opening a discovery call for a monetization platform",
                            good_example=(
                                "'I reviewed your pricing page and noticed you offer both "
                                "subscription and usage-based tiers. Can you walk me through "
                                "how your team manages the rating and billing for the usage "
                                "component today?'"
                            ),
                            bad_example=(
                                "'Tell me about your company. What do you do? How many "
                                "employees do you have?'"
                            ),
                            explanation=(
                                "The good example shows pre-call research and asks a targeted "
                                "question. The bad example wastes time on information available "
                                "on LinkedIn and signals lack of preparation."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Do your research before the call -- minimize basic situation questions",
                        "Use situation questions to confirm what you already know, not to start from scratch",
                        "Limit to 3-4 situation questions maximum before moving to problems",
                        "Frame situation questions as 'I noticed X, can you tell me more about...'",
                    ],
                ),
                MethodologyStep(
                    name="Problem",
                    abbreviation="P",
                    description=(
                        "Questions that uncover specific difficulties, dissatisfactions, or "
                        "challenges the customer experiences with their current situation. "
                        "These surface explicit pain points."
                    ),
                    purpose=(
                        "Problem questions move the conversation from facts to feelings. They "
                        "help the customer articulate what is not working and create the "
                        "foundation for exploring business impact."
                    ),
                    key_questions=[
                        "What is the most frustrating part of your current process?",
                        "Where do errors or delays typically occur?",
                        "What workarounds has your team had to build?",
                        "How satisfied are you with the accuracy of your current system?",
                        "What manual steps consume the most time for your team?",
                        "Are there capabilities your current solution lacks?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Uncovering problems with a legacy billing system",
                            good_example=(
                                "'You mentioned your team processes invoices manually for "
                                "usage-based customers. What happens when there are "
                                "discrepancies between the usage data and the invoice? "
                                "How often does that occur?'"
                            ),
                            bad_example=(
                                "'Are you having problems with your billing system?'"
                            ),
                            explanation=(
                                "The good example asks about a specific scenario and frequency, "
                                "making the problem concrete. The bad example is generic and "
                                "invites a dismissive 'it works fine' response."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Problem questions should reference specific situations, not generic categories",
                        "Ask about frequency and impact, not just existence of problems",
                        "Listen for emotional language (frustrated, concerned, worried) -- those signal real pain",
                        "If the customer says 'it works fine,' they are not your buyer. Probe deeper or qualify out.",
                    ],
                ),
                MethodologyStep(
                    name="Implication",
                    abbreviation="I",
                    description=(
                        "Questions that explore the consequences, ripple effects, and business "
                        "impact of the identified problems. Implication questions are the most "
                        "powerful part of SPIN because they make the customer feel the urgency."
                    ),
                    purpose=(
                        "Implication questions turn small problems into big ones by exploring "
                        "the downstream effects. They create urgency by helping the customer "
                        "see the full cost of inaction."
                    ),
                    key_questions=[
                        "What effect do those billing errors have on customer satisfaction?",
                        "How does this manual process impact your ability to scale?",
                        "When this system goes down, what is the impact on revenue recognition?",
                        "If this problem continues for another year, what is the cumulative cost?",
                        "How does this affect your team's ability to focus on strategic work?",
                        "What impact does this have on your competitive position?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Exploring implications of billing errors",
                            good_example=(
                                "'You mentioned billing errors create 15% of your support "
                                "tickets. Beyond support costs, how does that affect customer "
                                "trust? Have you seen any correlation between billing disputes "
                                "and churn rates?'"
                            ),
                            bad_example=(
                                "'So billing errors are a problem. Let me show you how our "
                                "platform fixes that.'"
                            ),
                            explanation=(
                                "The good example deepens the impact from support costs to "
                                "customer trust to churn -- each layer increases urgency. "
                                "The bad example skips the crucial implication exploration "
                                "and jumps to pitching."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Implication questions are where deals are won -- spend the most time here",
                        "Chain implications: 'If X leads to Y, what does that mean for Z?'",
                        "Help the customer calculate the cost of inaction themselves",
                        "The customer must feel the pain before they will value your solution",
                    ],
                ),
                MethodologyStep(
                    name="Need-Payoff",
                    abbreviation="N",
                    description=(
                        "Questions that get the customer to articulate the value and benefits "
                        "of solving the problem. Need-Payoff questions let the customer sell "
                        "themselves on the solution."
                    ),
                    purpose=(
                        "Need-Payoff questions shift the conversation from problems to "
                        "solutions in the customer's own words. When the customer describes "
                        "the benefit, they are more committed than when you describe it."
                    ),
                    key_questions=[
                        "If you could eliminate billing errors entirely, what would that mean for your team?",
                        "How would automating this process change your team's capacity?",
                        "What would it mean for customer satisfaction if invoices were always accurate?",
                        "If you could launch new pricing models in days instead of months, how would that affect your competitive position?",
                        "How valuable would it be to have real-time revenue visibility?",
                    ],
                    examples=[
                        MethodologyExample(
                            scenario="Transitioning from implications to need-payoff",
                            good_example=(
                                "'You mentioned billing errors cost $2M annually and contribute "
                                "to 5% incremental churn. If you could cut errors by 95% and "
                                "recover most of that churn, what would that mean for your "
                                "annual revenue targets?'"
                            ),
                            bad_example=(
                                "'Our platform eliminates 95% of billing errors and reduces "
                                "churn by 30%.'"
                            ),
                            explanation=(
                                "The good example gets the customer to articulate the value in "
                                "their own context and numbers. The bad example tells instead of "
                                "asks -- the customer is passive, not engaged."
                            ),
                        ),
                    ],
                    sales_stage="discovery",
                    tips=[
                        "Let the customer describe the benefit -- their words are more persuasive than yours",
                        "Need-Payoff questions work best after thorough implication exploration",
                        "Use the customer's own language when you later present your solution",
                        "If the customer cannot articulate the value, you have not explored implications deeply enough",
                    ],
                ),
            ],
            summary_checklist=[
                "Situation: Do you understand the customer's current environment and processes?",
                "Problem: Have you uncovered specific, concrete problems (not just general dissatisfaction)?",
                "Implication: Has the customer felt the full business impact of their problems?",
                "Need-Payoff: Has the customer articulated the value of solving the problem in their own words?",
            ],
        )
