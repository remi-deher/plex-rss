"""pubDate est la date d'ajout a la watchlist Plex (verifie empiriquement sur le
flux de production : les entrees sont triees par pubDate decroissant, sans
correlation avec l'annee de sortie des films/series) — pas la date de sortie
comme l'affirmait a tort un ancien commentaire. Voir plex_rss.py.
"""

from datetime import datetime

import feedparser

from app.services.plex_rss import _parse_rss_entry

RSS_ITEM = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
<item>
<title>Lee Cronin's The Mummy (2026)</title>
<author>c6a65fef3ad04865</author>
<category>movie</category>
<guid>imdb://tt32612507</guid>
<pubDate>Sun, 24 May 2026 21:02:57 GMT</pubDate>
</item>
</channel>
</rss>"""


def test_parse_rss_entry_uses_pubdate_as_requested_at():
    feed = feedparser.parse(RSS_ITEM)
    item = _parse_rss_entry(feed.entries[0])
    assert item["requested_at"] == datetime(2026, 5, 24, 21, 2, 57)


def test_parse_rss_entry_no_pubdate_leaves_requested_at_none():
    feed = feedparser.parse(
        RSS_ITEM.replace("<pubDate>Sun, 24 May 2026 21:02:57 GMT</pubDate>", "")
    )
    item = _parse_rss_entry(feed.entries[0])
    assert item["requested_at"] is None
