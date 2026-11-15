"""Punto de entrada para el hosting.

Los servidores de producción no ejecutan `python App.py`: importan este
archivo y usan la variable `application`.
"""

from App import app as application
