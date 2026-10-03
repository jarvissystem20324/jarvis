"""9.0 — the Design page: slides, posters, cards, logos and diagrams.

A design is plain JSON (see model.py): pages of elements — text, shapes,
lines, images, icons and tables — positioned in pixels of the design's own
size. One renderer (render.py) draws every page with Pillow, so what the
editor shows, the PNG/PDF exports and the chat previews are the same pixels;
pptxio.py maps the same elements onto real PowerPoint shapes and back.

The model writes content (headlines, bullet points, an org chart's people);
layout lives in templates.py and diagrams.py, so a design is legible however
small the model that planned it.
"""
