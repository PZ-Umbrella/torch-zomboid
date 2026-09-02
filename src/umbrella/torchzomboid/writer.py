from pathlib import Path
from operator import attrgetter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from albion.torch import Torch
from albion.torch.types import Class, AccessModifier, Type
from albion.torch.emmylua import LuaComment
from albion.torch.emmylua.writer import EmmyWriter, RESERVED_TYPE_NAMES
from albion.torch.emmylua.class_writer import EmmyClassWriter

from .exposer import KahluaExposer, VisibilityLevel, KahluaClass
from umbrella.torchzomboid import KAHLUA_METHOD_ANNOTATION, get_enclosing_classes

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


def get_class_table_name(clazz: Class) -> str:
    return clazz.name.replace("/", ".")


class KahluaWriter(EmmyWriter):
    def __init__(self) -> None:
        super().__init__()
        self.lua_name_map.update(KAHLUA_TYPE_MAP)

    def format_array(self, component_type: Type, dimensions: int) -> str:
        name = self.format_type(component_type)

        for _ in range(dimensions):
            name = f"kahlua.Array<{name}>"

        return name


class KahluaClassWriter(EmmyClassWriter):
    def __init__(self, writer: KahluaWriter, clazz: KahluaClass) -> None:
        super().__init__(writer, clazz.clazz)
        self.kahlua_class: Final = clazz

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
            case _:
                self.write_instance_members = False
                self.write_supers = False
                self.write_static_members = False

    def get_class_declaration(self) -> LuaComment:
        if self.kahlua_class.visibility_level is not VisibilityLevel.INVISIBLE:
            return super().get_class_declaration()
        else:
            return LuaComment()

    def get_class_description(self) -> LuaComment:
        description = LuaComment()

        if self.kahlua_class.visibility_level is not VisibilityLevel.EXPOSED:
            description.add_lines("(Not exposed)")

        return description + super().get_class_description()

    def write(self) -> str:
        string = super().write()

        if self.write_static_members:
            if string != "":
                string += "\n"
            string += (f"---@type Class<{self.clazz_name}>\n"
                       f"{self.identifier}.class = nil\n")

        if self.kahlua_class.visibility_level is VisibilityLevel.EXPOSED:
            if string != "":
                string += "\n"
            string += f"__classmetatables[{self.identifier}.class] = {{__index = __{self.identifier}}}\n"

        if self.kahlua_class.has_class_table:
            if string != "":
                string += "\n"
            table = self.identifier if self.write_static_members else "{}"
            string += f"{get_class_table_name(self.clazz)} = {table}\n"

        return string


def write_class(clazz: KahluaClass, writer: KahluaWriter) -> str:
    clazz_writer = KahluaClassWriter(writer, clazz)
    return clazz_writer.write()


def write_globals(classes: Iterable[Class], path: Path, writer: KahluaWriter) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write("---@meta _\n\n")
        for clazz in sorted(classes, key=attrgetter("name")):
            for method in sorted(clazz.get_all_methods(), key=attrgetter("name")):
                annotation = method.get_annotation(KAHLUA_METHOD_ANNOTATION)
                if annotation is None or not annotation.arguments.get("global", False):
                    continue

                name = annotation.arguments.get("name", method.name)

                comment = writer.annotate_method(method)

                string = writer.write_function(
                    name,
                    method.parameters
                )

                if not comment.is_empty():
                    string = str(comment) + "\n" + string

                file.write(
                    string + "\n"
                )


def write_kahlua_file(path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write(
            "---@meta _\n\n"
            "---@class kahlua.Array<T>\n\n"
            "__classmetatables = {}\n"
        )


def write_coop_server(path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write(
            "---@meta _\n\n"
            "CoopServer = {}\n\n"
            "---@param serverName string\n"
            "---@param userName string\n"
            "---@param memory number\n"
            "---@return boolean?\n"
            "function CoopServer.launch(serverName, userName, memory) end\n\n"
            "---@param serverName string\n"
            "---@param userName string\n"
            "---@param memory number\n"
            "---@return boolean?\n"
            "function CoopServer.softreset(serverName, userName, memory) end\n\n"
            "---@return boolean\n"
            "function CoopServer.isRunning() end\n\n"
            "---@param tag string\n"
            "---@param cookie string\n"
            "---@param payload string\n"
            "---@overload fun(tag: string, payload: string)\n"
            "function CoopServer.sendMessage(tag, cookie, payload) end\n\n"
            "---@return string\n"
            "function CoopServer.getAdminPassword() end\n\n"
            "---@return string\n"
            "function CoopServer.getTerminationReason() end\n\n"
            "---@return string?\n"
            "function CoopServer.getSteamID() end\n\n"
            "---@return string\n"
            "function CoopServer.getAddress() end\n\n"
            "---@return integer\n"
            "function CoopServer.getPort() end\n\n"
            "function CoopServer.abort() end\n\n"
            "---@param serverName string\n"
            "---@return string\n"
            "function getServerSaveFolder(serverName) end\n\n"
            "---@param serverName string\n"
            "---@return string\n"
            "function getPlayerSaveFolder(serverName) end\n"
        )


def write_voice_manager(path: Path) -> None:
    with path.open("w", encoding="utf-8") as file:
        file.write(
            "---@meta _\n\n"
            "VoiceManager = {}\n\n"
            "---@param username string\n"
            "function VoiceManager.playerSetMute(username) end\n\n"
            "---@param username string\n"
            "---@return boolean\n"
            "function VoiceManager.playerGetMute(username) end\n\n"
            "---@return string[]\n"
            "function VoiceManager.RecordDevices() end\n"
        )


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
                    and Type.is_primitive(field.type) and field.type.name == "int":
                file.write(f"---@type integer\nPZCalendar.{field.name} = nil\n\n")

        file.write("Calendar = PZCalendar\n")


@dataclass
class KahluaPackage:
    name: Final[str]
    exposed_classes: list[KahluaClass] = field(default_factory=list)
    exposed_subclasses: list[KahluaClass] = field(default_factory=list)
    visible_classes: list[KahluaClass] = field(default_factory=list)
    invisible_classes: list[KahluaClass] = field(default_factory=list)
    subpackages: list["KahluaPackage"] = field(default_factory=list)

    def should_render_package_file(self) -> bool:
        return len(self.visible_classes) > 0 or len(self.invisible_classes) > 0 or self.should_render_table()

    def should_render_table(self) -> bool:
        package_stack: list[KahluaPackage] = [self]
        while len(package_stack) > 0:
            package = package_stack.pop()
            if len(package.exposed_classes) > 0:
                return True
            package_stack += package.subpackages

        return False


def create_package_and_parents(packages: dict[str, KahluaPackage], name: str) -> None:
    parent_package = ""
    package = None
    for name_element in name.split("/"):
        parent_package += name_element
        if parent_package not in packages:
            packages[parent_package] = KahluaPackage(parent_package)
        if package is not None:
            package.subpackages.append(packages[parent_package])
        package = packages[parent_package]
        parent_package += "/"


def add_tables_for_enclosing_classes(clazz: KahluaClass, classes: dict[str, KahluaClass]) -> None:
    for enclosing_class in get_enclosing_classes(clazz.clazz.name):
        if enclosing_class not in classes:
            print(f"writer: missing enclosing class {enclosing_class} of exposed class {clazz.clazz.name}")
            continue
        classes[enclosing_class].has_class_table = True


def build_package_cache(classes: dict[str, KahluaClass], writer: KahluaWriter) -> dict[str, KahluaPackage]:
    packages: dict[str, KahluaPackage] = {}

    for clazz in classes.values():
        package_name = clazz.clazz.package()

        if clazz.clazz.name in KAHLUA_TYPE_MAP and clazz.visibility_level is not VisibilityLevel.EXPOSED:
            # only render lua classes that have exposed statics
            continue

        if package_name not in packages:
            create_package_and_parents(packages, package_name)

        package = packages[package_name]
        match clazz.visibility_level:
            case VisibilityLevel.EXPOSED:
                package.exposed_classes.append(clazz)
            case VisibilityLevel.EXPOSED_SUBCLASS:
                package.exposed_subclasses.append(clazz)
            case VisibilityLevel.VISIBLE:
                package.visible_classes.append(clazz)
            case VisibilityLevel.INVISIBLE:
                package.invisible_classes.append(clazz)

        # if the class already has a name in the map don't override it
        #  (mainly so we can override primitives with KAHLUA_TYPE_MAP)
        if clazz.clazz.name not in writer.lua_name_map:
            if clazz.name not in RESERVED_TYPE_NAMES:
                writer.lua_name_map[clazz.clazz.name] = clazz.name
            else:
                name = clazz.clazz.name.replace("/", ".").replace("$", ".")
                assert name not in RESERVED_TYPE_NAMES
                writer.lua_name_map[clazz.clazz.name] = name

        if clazz.has_class_table:
            add_tables_for_enclosing_classes(clazz, classes)

    return packages


def write_package(writer: KahluaWriter, path: Path, package: KahluaPackage) -> None:
    path.mkdir(parents=True, exist_ok=True)

    for clazz in package.exposed_classes + package.exposed_subclasses:
        with (path / (clazz.name + ".lua")).open("w", encoding="utf-8") as file:
            file.write("---@meta _\n\n" + write_class(clazz, writer))

    if package.should_render_package_file():
        with (path / "__package.lua").open("w", encoding="utf-8") as file:
            file.write("---@meta _\n")

            for clazz in sorted(package.visible_classes, key=attrgetter("name")):
                file.write("\n" + write_class(clazz, writer))

            if package.should_render_table():
                file.write(f"\n{package.name.replace("/", ".")} = {{}}\n")

            for clazz in sorted(package.invisible_classes, key=attrgetter("name")):
                file.write("\n" + write_class(clazz, writer))


def write_all(torch: Torch, path: Path, exposed_classes: Iterable[Class], exposed_globals: Iterable[Class]) -> None:
    exposer = KahluaExposer(torch)
    exposer.expose(exposed_classes)

    for clazz in exposed_globals:
        exposer.expose_visible_to_globals(clazz)

    write_kahlua_file(path / "__kahlua.lua")
    write_coop_server(path / "__CoopServer.lua")
    write_voice_manager(path / "__VoiceManager.lua")

    writer = KahluaWriter()

    # have to do this before writing globals because it builds the lua name map
    packages = build_package_cache(exposer.classes, writer)

    write_globals(exposed_globals, path / "__global.lua", writer)

    for package in packages.values():
        write_package(writer, path / package.name, package)

    write_calendar_file(path / "__Calendar.lua", torch)
