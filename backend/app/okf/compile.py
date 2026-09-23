"""Thin entry point so the documented command reads naturally.

    python -m app.okf.compile

All logic lives in app/okf/compiler.py.
"""

from app.okf.compiler import main

if __name__ == "__main__":
    main()
