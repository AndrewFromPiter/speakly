#!/usr/bin/env python3
"""
Точка входа для графического интерфейса Speakly.
"""

import sys
import os

# Добавляем src в путь
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.gui import run_gui

if __name__ == '__main__':
    run_gui()