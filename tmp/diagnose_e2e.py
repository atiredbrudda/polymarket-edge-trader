import sys

sys.path.insert(0, ".")
from src.config.settings import get_settings
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

settings = get_settings()
engine = create_engine(settings.database_url)

with Session(engine) as session:
    # Q1: Positions state
    r = session.execute(
        text(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved "
            "FROM positions"
        )
    ).fetchone()
    print(f"Positions: {r[0]} total, {r[1]} resolved")

    # Q2: Markets with outcome
    r = session.execute(
        text(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END) as has_outcome "
            "FROM markets"
        )
    ).fetchone()
    print(f"Markets: {r[0]} total, {r[1]} with outcome")

    # Q3: MarketClassification NULL taxonomy_node_id
    r = session.execute(
        text(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN taxonomy_node_id IS NULL THEN 1 ELSE 0 END) as null_node "
            "FROM market_classifications"
        )
    ).fetchone()
    print(f"MarketClassifications: {r[0]} total, {r[1]} with NULL taxonomy_node_id")

    # Q4: Game slugs with positions (this is what scoring pipeline uses)
    rows = session.execute(
        text(
            "SELECT tn.slug FROM taxonomy_nodes tn "
            "JOIN market_classifications mc ON mc.taxonomy_node_id = tn.id "
            "JOIN positions p ON p.market_id = mc.market_id "
            "WHERE tn.node_type = 'game' GROUP BY tn.slug"
        )
    ).fetchall()
    print(f"Game slugs with positions: {[r[0] for r in rows]}")

    # Q5: Xero100i trader
    r = session.execute(
        text(
            "SELECT COUNT(*) as pos_count, "
            "SUM(CASE WHEN resolved THEN 1 ELSE 0 END) as resolved "
            "FROM positions p "
            "WHERE p.trader_address = '0xeffd76b6a4318d50c6f71a16b276c5b279445a86'"
        )
    ).fetchone()
    print(f"Xero100i: {r[0]} positions, {r[1]} resolved")

    # Q6: token_catalog coverage
    r = session.execute(
        text(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN node_path IS NOT NULL THEN 1 ELSE 0 END) as classified "
            "FROM token_catalog WHERE niche_slug = 'esports'"
        )
    ).fetchone()
    print(f"Token catalog (esports): {r[0]} total, {r[1]} with node_path")
