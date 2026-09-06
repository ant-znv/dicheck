"""Корневой conftest pytest.

Нужен, чтобы корень проекта попал в sys.path при запуске pytest
(`.venv/Scripts/python.exe -X utf8 -m pytest backend/tests`) и импорты
`backend.app.*` работали без установки пакета. Фикстур здесь нет —
общие фикстуры живут в backend/tests/conftest.py.
"""
