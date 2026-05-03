"""Single source of truth for prop-market question patterns.

Imported by both the prune scripts and the ingestion-time filter.
Each entry: (label, sql LIKE pattern). Matched against LOWER(question).
"""

PROP_PATTERNS: list[tuple[str, str]] = [
    ("first_blood",         "%first blood%"),
    ("any_player_kill",     "%any player%kill%"),       # quadra/triple/penta/ultra/rampage
    ("any_player_rampage",  "%any player%rampage%"),
    ("both_teams_slay",     "%both teams slay%"),       # dragon, baron nashor, etc.
    ("both_teams_destroy",  "%both teams destroy%"),    # inhibitors, turrets, etc.
    ("total_kills_ou",      "%total kills over/under%"),
    ("total_kills_game",    "game % total kills%"),     # "Game N: Total Kills..."
    ("odd_even_kills",      "%odd/even total kills%"),
    ("games_total_ou",      "games total: o/u%"),
    ("kill_handicap",       "%kill handicap%"),
    ("to_win_n_games",      "% to win % games?%"),      # "X to win 2 games?" series prop
    ("both_teams_beat",     "%both teams beat%"),       # "Both Teams Beat Roshan?"
    ("odd_even_rounds",     "%odd/even total rounds%"), # CS-specific round-count prop
]
