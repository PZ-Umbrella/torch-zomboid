from typing import Final

KAHLUA_METHOD_ANNOTATION: Final = "se/krka/kahlua/integration/annotations/LuaMethod"


def get_enclosing_classes(clazz_name: str) -> list[str]:
    enclosing_classes: list[str] = []

    dot_pos = clazz_name.rfind(".")
    while dot_pos != -1:
        clazz_name = clazz_name[:dot_pos]
        enclosing_classes.append(clazz_name)
        dot_pos = clazz_name.rfind(".")

    return enclosing_classes

def uv_main() -> None:
    from umbrella.torchzomboid.cli import main
    main()

def uv_edit() -> None:
    from umbrella.torchzomboid.editor import main
    main()
