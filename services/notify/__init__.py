"""Notification layer: providers, dispatcher, and the record store behind the console.

Sits strictly downstream of the prediction system — it reads finished forecast/area
files and never touches the models or rules/engine.py.
"""
