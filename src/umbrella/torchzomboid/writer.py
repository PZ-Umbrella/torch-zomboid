from pathlib import Path
from operator import attrgetter
from collections.abc import Iterable
from dataclasses import dataclass, field

from albion.torch import Torch, TypeReference
from albion.torch.types import Class, AccessModifier
from albion.torch.emmylua import LuaComment
from albion.torch.emmylua.writer import EmmyWriter, RESERVED_TYPE_NAMES
from albion.torch.emmylua.class_writer import EmmyClassWriter

from .exposer import KahluaExposer, VisibilityLevel, KahluaClass


KAHLUA_TYPE_MAP = {
    "boolean": "boolean",
    "java/lang/Boolean": "boolean",
    "void": "null",

    "byte": "integer",
    "java/lang/Byte": "integer",
    "char": "integer",
    "java/lang/Char": "integer",
    "short": "integer",
    "java/lang/Short": "integer",
    "int": "integer",
    "java/lang/Integer": "integer",
    "long": "integer",
    "java/lang/Long": "integer",

    "float": "number",
    "java/lang/Float": "number",
    "double": "number",
    "java/lang/Double": "number",

    "java/lang/String": "string",
    "java/lang/Object": "any",

    "se/krka/kahlua/vm/KahluaTable": "table",
    "se/krka/kahlua/vm/LuaClosure": "function",
    "se/krka/kahlua/j2se/KahluaTableImpl": "table"
}


class KahluaWriter(EmmyWriter):
    def format_type(self, _type: TypeReference) -> str:
        basic = _type.basic

        if basic in KAHLUA_TYPE_MAP:
            name = KAHLUA_TYPE_MAP[basic]
        else:
            name = super().format_type(_type)

        for _ in range(_type.array_dimensions):
            name = f"kahlua.Array<{name}>"

        return name


class KahluaClassWriter(EmmyClassWriter):
    def __init__(self, writer: KahluaWriter, clazz: KahluaClass, visibility_level: VisibilityLevel) -> None:
        super().__init__(writer, clazz.clazz)
        self.visibility_level: VisibilityLevel = visibility_level

        match clazz.visibility_level:
            case VisibilityLevel.EXPOSED:
                self.write_instance_members = True
                self.write_static_members = True
                self.write_supers = True
            case VisibilityLevel.EXPOSED_SUBCLASS:
                self.write_instance_members = True
                self.write_supers = True
                self.write_static_members = False
            case VisibilityLevel.VISIBLE:
                self.write_instance_members = False
                self.write_supers = False
                self.write_static_members = False

    def get_class_description(self) -> LuaComment:
        description = LuaComment()

        if self.visibility_level < VisibilityLevel.EXPOSED:
            description.add_lines("(Not exposed)")

        return description + super().get_class_description()


def write_class(clazz: KahluaClass, writer: KahluaWriter) -> str:
    if clazz.visibility_level == VisibilityLevel.NONE:
        return ""

    clazz_writer = KahluaClassWriter(writer, clazz, clazz.visibility_level)

    return clazz_writer.write()


def write_globals(classes: Iterable[Class], path: Path, writer: KahluaWriter) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write("---@meta _\n\n")
        for clazz in sorted(classes, key=attrgetter("name")):
            for method in sorted(clazz.get_all_methods(), key=attrgetter("name")):
                annotation = method.get_annotation("se/krka/kahlua/integration/annotations/LuaMethod")
                if annotation is None or not annotation.arguments.get("global", False):
                    continue

                name = annotation.arguments.get("name", method.name)

                comment = writer.annotate_method(method)

                string = writer.write_function(
                    name,
                    writer.get_parameter_names(method)
                )

                if not comment.is_empty():
                    string = str(comment) + "\n" + string

                file.write(
                    string + "\n"
                )


def write_kahlua_file(path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write("---@meta\n\n"
                   "---@class kahlua.Array<T>\n\n"
                   "__classmetatables = {}\n")


def write_calendar_file(path: Path, torch: Torch) -> None:
    calendar = torch.get_class("java/util/Calendar")

    if calendar is None:
        print("Cannot expose Calendar because java/util/Calendar is not known.")
        return

    with path.open("w", encoding="utf-8") as file:
        file.write("---@meta _\n\n")

        for field in calendar.fields.values():
            # TODO: should check if final, but we don't store this currently
            if field.static and field.access_modifier is AccessModifier.PUBLIC \
                    and field.type.basic == "int" and field.type.array_dimensions == 0:
                file.write(f"---@type integer\nPZCalendar.{field.name} = nil\n\n")

        file.write("Calendar = PZCalendar\n")


@dataclass
class PackageCache:
    name: str
    exposed_classes: list[KahluaClass] = field(default_factory=list)
    exposed_subclasses: list[KahluaClass] = field(default_factory=list)
    visible_classes: list[KahluaClass] = field(default_factory=list)
    subpackages: list["PackageCache"] = field(default_factory=list)

    def should_render_table(self) -> bool:
        package_stack: list[PackageCache] = [self]
        while len(package_stack) > 0:
            package = package_stack.pop()
            if len(package.exposed_classes) > 0:
                return True
            package_stack += package.subpackages

        return False


def write_all(torch: Torch, path: Path, exposed_classes: Iterable[Class], exposed_globals: Iterable[Class]) -> None:
    exposer = KahluaExposer(torch)
    exposer.expose(exposed_classes)

    for clazz in exposed_globals:
        exposer.expose_visible_to_globals(clazz)

    write_kahlua_file(path / "__kahlua.lua")

    writer = KahluaWriter()

    packages: dict[str, PackageCache] = {}

    for clazz in exposer.classes.values():
        package_name = clazz.clazz.package()

        if package_name not in packages:
            parent_package = ""
            package = None
            for package_element in package_name.split("/"):
                parent_package += package_element
                if parent_package not in packages:
                    packages[parent_package] = PackageCache(parent_package)
                if package is not None:
                    package.subpackages.append(packages[parent_package])
                package = packages[parent_package]
                parent_package += "/"

        package = packages[package_name]
        match clazz.visibility_level:
            case VisibilityLevel.EXPOSED:
                package.exposed_classes.append(clazz)
            case VisibilityLevel.EXPOSED_SUBCLASS:
                package.exposed_subclasses.append(clazz)
            case VisibilityLevel.VISIBLE:
                package.visible_classes.append(clazz)
        if clazz.name not in RESERVED_TYPE_NAMES:
            writer.lua_name_map[clazz.clazz.name] = clazz.name
        else:
            name = clazz.clazz.name.replace("/", ".").replace("$", ".")
            assert name not in RESERVED_TYPE_NAMES
            writer.lua_name_map[clazz.clazz.name] = name

    write_globals(exposed_globals, path / "__global.lua", writer)

    for package in packages.values():
        package_path = path / package.name
        package_path.mkdir(parents=True, exist_ok=True)

        for clazz in package.exposed_classes + package.exposed_subclasses:
            with (package_path / (clazz.name + ".lua")).open("w", encoding="utf-8") as file:
                file.write("---@meta _\n\n" + write_class(clazz, writer))

        if len(package.visible_classes) > 0 or package.should_render_table():
            with (package_path / "__package.lua").open("w", encoding="utf-8") as file:
                file.write("---@meta _\n\n")
                if package.should_render_table():
                    file.write(f"{package.name.replace("/", ".")} = {{}}\n")

                for clazz in sorted(package.visible_classes, key=attrgetter("name")):
                    file.write("\n" + write_class(clazz, writer))

    write_calendar_file(path / "__Calendar.lua", torch)
