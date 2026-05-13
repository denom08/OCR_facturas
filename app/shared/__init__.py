"""Utilidades compartidas."""

# Los módulos de logging, debug_info y money se importan directamente
# donde se necesitan. Las re-exportaciones aquí causarían F401 en ruff
# porque el __init__ no las consume directamente.