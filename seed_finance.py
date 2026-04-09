"""Seed the Financial Theory section with book roadmap, skills roadmap, and 12-month study plan."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lifeoptimization.db')
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
conn.execute('PRAGMA foreign_keys = ON')

# Get status IDs
statuses = {r['color']: r['id'] for r in conn.execute('SELECT * FROM statuses').fetchall()}
GREEN = statuses['green']    # Currently Have / In Progress
BLUE = statuses['blue']      # Next Up
ORANGE = statuses['orange']  # Eventual
RED = statuses['red']        # Needs Attention

# ── 1. Create sidebar section ──
existing = conn.execute("SELECT id FROM sidebar_sections WHERE page_key='custom_financial_theory'").fetchone()
if not existing:
    max_order = conn.execute('SELECT MAX(sort_order) FROM sidebar_sections').fetchone()[0] or 0
    conn.execute(
        "INSERT INTO sidebar_sections (group_name, label, page_key, sort_order, is_builtin) VALUES (?,?,?,?,0)",
        ('Academic', 'Financial Theory', 'custom_financial_theory', max_order + 1))
    conn.commit()
    print("Created sidebar section: Financial Theory")
else:
    print("Sidebar section already exists, clearing old items...")
    conn.execute("DELETE FROM custom_items WHERE section_key='custom_financial_theory'")
    conn.commit()

SK = 'custom_financial_theory'
order = 0

def add(name, status, notes=''):
    global order
    order += 1
    conn.execute(
        'INSERT INTO custom_items (section_key, name, status_id, notes, sort_order) VALUES (?,?,?,?,?)',
        (SK, name, status, notes, order))

# ══════════════════════════════════════════════════════════════
# PART 1: BOOK ROADMAP
# ══════════════════════════════════════════════════════════════

add('━━━ BOOK ROADMAP ━━━', GREEN,
    'Sequenced reading list from current level to high-level finance.')

# Current
add('📖 [CURRENT] Essentials of Corporate Finance — Ross, Westerfield, Jordan', GREEN,
    'Chapter 11 completed (Risk & Return, Portfolio Variance). ~60% of bachelor-level foundation. Finish chapters 12-15 next.')

# Phase 1: Sophomore/Junior
add('📘 Phase 1: Corporate Finance — Ross, Westerfield, Jaffe (Full Text)', BLUE,
    'The "big brother" to Essentials. Covers Capital Structure (MM Prop I & II), Dividend Policy, Advanced Valuation. Required before options/derivatives.')

# Phase 2: Analyst Level
add('📘 Phase 2: Investment Banking — Rosenbaum & Pearl', ORANGE,
    'Valuation, LBOs, M&A. Teaches model building. The bible for IB/ER/PE entry-level roles.')

# Phase 3: Associate Level
add('📘 Phase 3: Options, Futures & Other Derivatives — John Hull', ORANGE,
    'Portfolio variance → Beta → Hedging. Gold standard for pricing risk. Start with chapters 1-10.')

# Phase 4: VP/Director Level
add('📙 Phase 4a: The Intelligent Investor — Benjamin Graham', ORANGE,
    'Value investing philosophy. How to think about intrinsic value vs. market price.')

add('📙 Phase 4b: Thinking, Fast and Slow — Daniel Kahneman', ORANGE,
    'Cognitive biases in markets. Prospect theory, overconfidence, anchoring. Critical for behavioral finance.')

add('📙 Phase 4c: The Alchemy of Finance — George Soros', ORANGE,
    'Reflexivity and macro thinking. How feedback loops move markets beyond fundamentals.')

# Capstone
add('📕 Capstone: Active Portfolio Management — Grinold & Kahn', ORANGE,
    'PhD-level. Read first 3 chapters for the Fundamental Law of Active Management. α = IC × √BR × σ.')

# ══════════════════════════════════════════════════════════════
# PART 2: SKILLS & TOPICS ROADMAP
# ══════════════════════════════════════════════════════════════

add('━━━ SKILLS ROADMAP ━━━', GREEN,
    'From portfolio variance to high-level pillars. Each level builds on the last.')

# Level 1 — Current
add('🟢 L1: Portfolio Variance & Covariance [YOU ARE HERE]', GREEN,
    'σ²p = w₁²σ₁² + w₂²σ₂² + 2w₁w₂Cov(R₁,R₂)\n'
    'Skill: Calculate 2-asset portfolio variance by hand.\n'
    'Key Q: Why does a negatively correlated asset reduce total risk even if volatile?')

# Level 2
add('🔵 L2: Matrix Algebra & Multi-Asset Variance', BLUE,
    'σ²p = wᵀΣw (matrix notation for N assets).\n'
    'Skill: 5+ asset portfolio variance using matrices.\n'
    'Tools: Excel MMULT/MINVERSE or Python NumPy.\n'
    'Timeline: Next 2 weeks.')

# Level 3
add('🔵 L3: Efficient Frontier & CAPM', BLUE,
    'Plot the efficient frontier. Find the Tangency Portfolio (max Sharpe Ratio).\n'
    'β = Cov(Rᵢ, Rₘ) / σ²ₘ\n'
    'The Market Portfolio = theoretical tangency point.\n'
    'Timeline: 1 month.')

# Level 4
add('🟠 L4: Risk Decomposition & Attribution', ORANGE,
    'Total Variance = Systematic (β²σ²ₘ) + Idiosyncratic (σ²ε).\n'
    'Skill: Answer "Did we lose money because the market crashed (luck) or stock picks were bad (skill)?"\n'
    'Timeline: 3 months.')

# Level 5 Pillars
add('🟠 L5 Pillar: Corporate Finance', ORANGE,
    'WACC, APV, FCF, LBO Models.\n'
    'High-level Q: "How do we finance a $1B acquisition without bankrupting the firm?"')

add('🟠 L5 Pillar: Derivatives', ORANGE,
    'Black-Scholes, Greeks, Swaps.\n'
    'High-level Q: "How do we hedge fuel cost risk for an airline?"')

add('🟠 L5 Pillar: Fixed Income', ORANGE,
    'Duration, Convexity, Credit Spreads.\n'
    'High-level Q: "If rates rise 1%, how much does our $10B bond portfolio lose?"')

add('🟠 L5 Pillar: Macroeconomics', ORANGE,
    'Taylor Rule, Yield Curve, Carry Trade.\n'
    'High-level Q: "Is the Fed tightening? Should we be in cash or equities?"')

add('🟠 L5 Pillar: Behavioral Finance', ORANGE,
    'Prospect Theory, Overconfidence, Herding.\n'
    'High-level Q: "The model says buy but everyone is selling. What is the real price?"')

# ══════════════════════════════════════════════════════════════
# PART 3: 12-MONTH STUDY PLAN
# ══════════════════════════════════════════════════════════════

add('━━━ 12-MONTH STUDY PLAN ━━━', GREEN,
    'Practical milestones from student to PM candidate.')

add('📅 Months 1-3: Quant Foundation', BLUE,
    'Goal: Portfolio Variance → CAPM → WACC.\n'
    'DO: Build 5-stock portfolio in Excel. Calculate daily variance. Calculate β vs S&P 500.\n'
    'Book: Finish current book chapters 12-15.')

add('📅 Months 4-6: Valuation Intensive', ORANGE,
    'Goal: Project future cash flows. Discount them back.\n'
    'DO: Build a 3-statement model for one public company (e.g. Apple or a bank).\n'
    'Book: Rosenbaum & Pearl (Investment Banking).')

add('📅 Months 7-9: Risk Professional', ORANGE,
    'Goal: Understand optionality and fixed income math.\n'
    'DO: Model a Call/Put payoff. Calculate bond duration.\n'
    'Book: Hull chapters 1-10.')

add('📅 Months 10-12: Portfolio Manager Lite', ORANGE,
    'Goal: Allocate capital across 10 assets to maximize Sharpe Ratio.\n'
    'DO: Use Python scipy.optimize to find the efficient frontier.\n'
    'Book: Grinold & Kahn (first 3 chapters).')

add('💡 The Meta-Skill', GREEN,
    '"Excel is the shovel. Python is the backhoe. Storytelling is the gold."\n'
    'High-level finance = telling the CFO: "Our variance is high because we\'re concentrated in Tech,\n'
    'but expected return compensates. Here is the 5% worst-case scenario."')

add('⚡ TODAY\'S ACTION', RED,
    'Take 2 stocks (e.g. Apple + Gold ETF). Calculate portfolio variance.\n'
    'Then: What weight minimizes variance? (Set derivative of variance formula = 0).\n'
    'Do this and you are ahead of 80% of students.')

conn.commit()
total = conn.execute("SELECT COUNT(*) FROM custom_items WHERE section_key=?", (SK,)).fetchone()[0]
print(f"Seeded {total} items into Financial Theory section.")
conn.close()
