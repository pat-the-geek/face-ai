"""HTML fixtures pour tests scraper."""

# Page article minimaliste avec 3 images :
# - 1 figure avec figcaption mentionnant "Sam Altman" → match
# - 1 img.alt mentionne "Elon Musk" → match
# - 1 img sans alt ni caption → ignored
# - 1 img avec src relatif → URL absolue résolue via base
ARTICLE_HTML = """
<!doctype html>
<html lang="fr">
<head><title>Test article</title></head>
<body>
  <h1>Article test</h1>

  <figure>
    <img src="https://cdn.example.com/altman1.jpg" alt="portrait" />
    <figcaption>Sam Altman lors de la conférence</figcaption>
  </figure>

  <p>Contenu du paragraphe.</p>

  <img src="https://cdn.example.com/musk1.jpg" alt="Elon Musk au Forum" />

  <img src="https://cdn.example.com/photo.jpg" />

  <img src="/static/relative.jpg" alt="Sam Altman au TED" />

  <img src="data:image/png;base64,iVBORw0KG..." alt="ignored data URL" />
</body>
</html>
"""

# Page sans aucune image
ARTICLE_HTML_EMPTY = "<html><body><p>texte sans image</p></body></html>"
