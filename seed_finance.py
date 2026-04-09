"""Seed the Financial Theory section with an expanded day-by-day long-term objective roadmap."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lifeoptimization.db')
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA foreign_keys = ON')

# Get status IDs
statuses = {r['color']: r['id'] for r in conn.execute('SELECT * FROM statuses').fetchall()}
GREEN = statuses['green']
BLUE = statuses['blue']
ORANGE = statuses['orange']
RED = statuses['red']

# ── 1. Create sidebar section ──
existing = conn.execute("SELECT id FROM sidebar_sections WHERE page_key='custom_financial_theory'").fetchone()
if not existing:
    max_order = conn.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
    conn.execute(
        "INSERT INTO sidebar_sections (group_name, label, page_key, sort_order, is_builtin, is_long_term_section) VALUES (?,?,?,?,0,1)",
        ('Academic', 'Financial Theory', 'custom_financial_theory', max_order + 1))
    conn.commit()
    print("Created sidebar section: Financial Theory")
else:
    print("Sidebar section already exists, clearing old items...")
    conn.execute("UPDATE sidebar_sections SET is_long_term_section=1 WHERE page_key='custom_financial_theory'")
    conn.execute("DELETE FROM custom_items WHERE section_key='custom_financial_theory'")
    conn.commit()

SK = 'custom_financial_theory'
order = 0

def add(name, status, notes='', is_long_term_objective=0):
    global order
    order += 1
    conn.execute(
        'INSERT INTO custom_items (section_key, name, status_id, notes, sort_order, is_long_term_objective) VALUES (?,?,?,?,?,?)',
        (SK, name, status, notes, order, is_long_term_objective))

# ===== Executive assumptions and operating cadence =====
add('━━━ EXECUTION ASSUMPTIONS ━━━', GREEN,
    'Expanded Financial Theory roadmap converted into day-by-day long-term objectives with checkpoints and certifications.')
add('Baseline weekly commitment', GREEN,
    'Weekdays: 1.5h/day. Saturday: 3h. Sunday: off/review only. Total ~10.5h/week.')
add('Program start anchor', BLUE,
    'Assumed start: Monday, April 14, 2026. Shift all dates if your actual start changes.')
add('Retention rule', GREEN,
    'Every 7th day is review only. No new material on review day.')
add('Total horizon to PM-ready', BLUE,
    '~12 months, ~450 total study hours with review and buffer days included.')

# ===== Phase 0 =====
add('━━━ PHASE 0: COMPLETE ESSENTIALS OF CORPORATE FINANCE ━━━', GREEN,
    'Status: in progress. Chapter 11 complete. Target: finish chapters 12-15 + review.')
add('Chapter 12: Cost of Capital (WACC)', GREEN,
    '3 days / 4.5h. Day 1 read + problems 1-5. Day 2 problems 6-10 + Excel WACC on a real company. Day 3 teach-back + error review.', 1)
add('Chapter 13: Leverage and Capital Structure', BLUE,
    '4 days / 6h. Focus on debt/equity impact and cost of equity mechanics.', 1)
add('Chapter 14: Dividends and Payout Policy', BLUE,
    '2 days / 3h. Compare dividends vs buybacks and policy effects on value.', 1)
add('Chapter 15: Raising Capital', BLUE,
    '2 days / 3h. Equity issuance, debt issuance, and financing path selection.', 1)
add('Phase 0 review sprint', GREEN,
    '1 review day / 1.5h covering chapters 11-15. Goal: compute WACC for any public company in under 10 minutes.', 1)

# ===== Phase 1 =====
add('━━━ PHASE 1: CORPORATE FINANCE DEEP (ROSS, WESTERFIELD, JAFFE) ━━━', BLUE,
    'Duration: 6 weeks (42 days). Study time ~65h.')
add('Week 1-2: MM Propositions and capital structure', BLUE,
    'Day 1 MM Prop I (no taxes). Day 2 MM Prop II: re = r0 + (D/E)(r0-rd). Day 3 tax shield tc*D. Day 4 bankruptcy costs. Day 5 pecking order. Day 6 practice set. Day 7 memory re-derivation.', 1)
add('Week 3-4: Advanced valuation', ORANGE,
    'APV build-out, FCF vs equity FCF, changing debt structures, then a 2-hour mini exam.', 1)
add('Week 5-6: Dividend policy and special topics', ORANGE,
    'Dividend irrelevance, repurchases vs dividends, lease-vs-buy, M&A valuation, restructuring, then review week.', 1)
add('Phase 1 checkpoint', GREEN,
    'You can value a leveraged buyout structure on paper and defend capital structure choices.', 1)

# ===== Phase 2 =====
add('━━━ PHASE 2: INVESTMENT BANKING / VALUATION (ROSENBAUM AND PEARL) ━━━', BLUE,
    'Duration: 8 weeks (56 days). Study time ~90h.')
add('Weeks 1-2: Core valuation methods', BLUE,
    'Build DCF from scratch, then trading comps, then precedent transactions template.', 1)
add('Weeks 3-4: LBO modeling', ORANGE,
    'Sources and uses, debt schedules, IRR and MOIC return stack.', 1)
add('Weeks 5-6: M&A modeling', ORANGE,
    'Accretion/dilution, pro forma balance sheet, synergy valuation.', 1)
add('Weeks 7-8: Integration and case', ORANGE,
    'Build full 3-statement model, then complete LBO case under time pressure.', 1)
add('Phase 2 checkpoint', GREEN,
    'Build a 3-statement LBO model in under 2 hours.', 1)
add('Certification: FMVA (CFI)', BLUE,
    'Cost ~$497. Typical prep 40-60h. Best attempted immediately after Phase 2.', 1)

# ===== Phase 3 =====
add('━━━ PHASE 3: DERIVATIVES AND RISK (JOHN HULL) ━━━', ORANGE,
    'Duration: 10 weeks (70 days). Study time ~105h.')
add('Weeks 1-2: Forwards and futures foundations', BLUE,
    'Mechanics, hedge ratio, and interest-rate futures basics.', 1)
add('Weeks 3-5: Options and pricing core', ORANGE,
    'Put-call parity, binomial trees, Black-Scholes intuition, and Greeks.', 1)
add('Weeks 6-8: Swaps and advanced derivatives', ORANGE,
    'Interest-rate swaps, currency swaps, CDS intro, exotic options overview.', 1)
add('Weeks 9-10: Risk integration', ORANGE,
    'Build payoff sheets, run practical hedging scenarios (e.g., airline fuel hedge), and complete review problem sets.', 1)
add('Phase 3 checkpoint', GREEN,
    'Manually delta-hedge a call option and explain hedge drift.', 1)
add('Certification: FRM Part I (GARP)', ORANGE,
    'Cost ~$850. Add ~100h focused question practice after this phase. Target May/Nov sitting.', 1)

# ===== Phase 4 =====
add('━━━ PHASE 4: BEHAVIORAL AND MACRO (GRAHAM, KAHNEMAN, SOROS) ━━━', ORANGE,
    'Duration: 6 weeks (42 days). Study time ~45h. Lighter but conceptually critical.')
add('Weeks 1-2: Value investing foundations', BLUE,
    'Mr. Market, margin of safety, defensive vs enterprising investor.', 1)
add('Weeks 3-4: Cognitive bias stack', ORANGE,
    'Prospect theory, overconfidence, anchoring; map each to real investment mistakes.', 1)
add('Weeks 5-6: Reflexivity and macro casework', ORANGE,
    'Boom-bust feedback loops, macro trade case notes, and a 2-page personal investment philosophy.', 1)
add('Phase 4 checkpoint', GREEN,
    'Identify at least 3 cognitive biases in any real stock pitch and propose mitigation.', 1)

# ===== Phase 5 =====
add('━━━ PHASE 5: ACTIVE PORTFOLIO MANAGEMENT (GRINOLD AND KAHN) ━━━', ORANGE,
    'Duration: 8 weeks (56 days). Study time ~90h.')
add('Weeks 1-2: Fundamental Law and signal quality', BLUE,
    'IR = IC * sqrt(BR), transfer coefficient effects, and constraint drag.', 1)
add('Weeks 3-5: Portfolio construction engine', ORANGE,
    'Alpha assumptions, risk model basics, constrained optimization, turnover and transaction costs.', 1)
add('Weeks 6-8: Python implementation and capstone', ORANGE,
    'Efficient frontier in Python (scipy.optimize), practical constraints, backtest, realized vs expected IR analysis.', 1)
add('Phase 5 checkpoint', GREEN,
    'Deliver Python optimizer for a 10-asset portfolio targeting max Sharpe with constraints.', 1)
add('Certification: CIPM or FRM Part II', ORANGE,
    'Typical cost around $1,000. Add 100-150h prep after capstone outputs are stable.', 1)

# ===== Certification roadmap =====
add('━━━ CERTIFICATION ROADMAP (INTEGRATED) ━━━', BLUE,
    'Use certifications to validate applied skill after each technical phase, not before.')
add('Month 3 target: FMVA', BLUE,
    'Cost ~$497. Prep 40-60h. Best after valuation/LBO phase.', 1)
add('Month 6 target: FRM Part I', ORANGE,
    'Cost ~$850. Add 100h question practice after derivatives phase.', 1)
add('Month 9 target: no credential', GREEN,
    'Focus on portfolio build and case execution. Skill compounding over certificates.', 1)
add('Month 12 target: CIPM or FRM Part II', ORANGE,
    'Cost ~$1,000. Prep 100-150h after active PM capstone.', 1)
add('CFA sequencing note', GREEN,
    'CFA is intentionally deferred. This roadmap first, then evaluate CFA necessity based on role requirements.', 1)

# ===== Adjusted daily and weekly execution =====
add('━━━ ADJUSTED DAILY STUDY SCHEDULE ━━━', GREEN,
    'Adjusted for consistency and retention with lower burnout risk.')
add('Morning review block (6:30-7:00 AM)', GREEN,
    'Spaced repetition only. Re-write formulas and definitions from memory.', 1)
add('Midday concept block (12:00-12:30 PM)', BLUE,
    'Read new material while alert. No heavy problem solving in this block.', 1)
add('Evening build block (7:00-8:00 PM)', ORANGE,
    'Problem sets, Excel builds, and Python implementation.', 1)
add('One-block fallback option', GREEN,
    'If day gets compressed, do one 90-minute block: 7:00-8:30 PM or 6:00-7:30 AM.', 1)
add('Sleep/retention guardrail', RED,
    'Avoid studying after 10 PM. Memory consolidation quality declines with late-night heavy study.', 1)

add('━━━ WEEKLY TEMPLATE (PRINTABLE) ━━━', BLUE,
    'Repeat this cadence each week and only adjust workload, not structure.')
add('Monday template', GREEN,
    'Read chapter/subchapter (45m) + solve first 5 problems (45m).', 1)
add('Tuesday template', GREEN,
    'Remaining problems (45m) + Excel build (45m).', 1)
add('Wednesday template', BLUE,
    'Extend model with sensitivities (60m) + teach-back drill (30m).', 1)
add('Thursday template', BLUE,
    'Read next subsection (45m) + flashcards/recall drill (45m).', 1)
add('Friday template', ORANGE,
    'Mixed problem set from prior chapters (90m).', 1)
add('Saturday template', ORANGE,
    '3-hour mini case build from scratch.', 1)
add('Sunday template', GREEN,
    'Off day or controlled catch-up only.', 1)

# ===== Duration table converted into objectives =====
add('━━━ PHASE DURATION TARGETS (REALISTIC) ━━━', BLUE,
    'Use this to pressure-test pacing and identify slippage early.')
add('Phase 0 target', GREEN, '18h study, ~12 calendar days, ~2 weeks with buffer.', 1)
add('Phase 1 target', BLUE, '65h study, ~43 days, ~6 weeks with review cadence.', 1)
add('Phase 2 target', ORANGE, '90h study, ~60 days, ~8 weeks with modeling repetitions.', 1)
add('Phase 3 target', ORANGE, '105h study, ~70 days, ~10 weeks including practice.', 1)
add('Phase 4 target', GREEN, '45h study, ~30 days, ~6 weeks lighter conceptual phase.', 1)
add('Phase 5 target', ORANGE, '90h study, ~60 days, ~8 weeks implementation-heavy.', 1)
add('Program-level target', BLUE, '413 core hours, ~275 days, ~10.5 months with buffers.', 1)

# ===== Today action pack =====
add('━━━ TODAY\'S ACTION PACK (START DAY) ━━━', RED,
    'Immediate execution plan for Day 1 to break inertia and establish momentum.')
add('Morning action', GREEN,
    'Write portfolio variance formula from memory and explain each term aloud.', 1)
add('Midday action', BLUE,
    'Open Excel and load 60 daily returns for AAPL and GLD.', 1)
add('Evening action', RED,
    'Compute variance(AAPL), variance(GLD), covariance, and portfolio variance at w=(0.5,0.5). Then solve minimum-variance weight.', 1)
add('Minimum variance formula objective', ORANGE,
    'w_min = (sigma2^2 - Cov) / (sigma1^2 + sigma2^2 - 2*Cov). Verify numerically in Excel.', 1)
add('Execution standard', GREEN,
    'If completed today, you are ahead of most students because you moved from reading to quant execution.', 1)

conn.commit()
total = conn.execute("SELECT COUNT(*) FROM custom_items WHERE section_key=?", (SK,)).fetchone()[0]
print(f"Seeded {total} items into Financial Theory section.")
conn.close()
