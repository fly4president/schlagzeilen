# Meine Schlagzeilen

Eigene Nachrichten-App als Ersatz für Google News, ohne Werbung und ohne Algorithmus.

- `feeds.json`: die Quellen. Neue Quelle = neue Zeile mit Name, Kategorie und RSS-Adresse.
- `fetch_news.py`: holt alle Feeds und schreibt `docs/news.json`.
- `docs/`: die App selbst, veröffentlicht über GitHub Pages.
- `.github/workflows/update.yml`: führt den Abruf alle 20 Minuten automatisch bei GitHub aus.
