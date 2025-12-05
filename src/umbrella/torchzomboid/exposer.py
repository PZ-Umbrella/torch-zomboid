import enum

from collections.abc import Iterable
from dataclasses import dataclass

from albion.torch import Torch
from albion.torch.types import Class, TypeReference, Method, PRIMITIVE_TYPE_NAMES
from albion.torch.util import OrderedEnum

from umbrella.torchzomboid import KAHLUA_METHOD_ANNOTATION, get_enclosing_classes


class VisibilityLevel(OrderedEnum):
    INVISIBLE = enum.auto()
    """Not visible at all."""
    VISIBLE = enum.auto()
    """
    Appears in the type, parameters, return type or type argument of an exposed object.
    """
    EXPOSED_SUBCLASS = enum.auto()
    """Has an exposed child class."""
    EXPOSED = enum.auto()
    """Exposed by the exposer."""


@dataclass
class KahluaClass:
    clazz: Class
    name: str
    visibility_level: "VisibilityLevel"
    has_class_table: bool


def is_global_method(method: Method) -> bool:
    annotation = method.get_annotation(KAHLUA_METHOD_ANNOTATION)
    if annotation is not None:
        return annotation.arguments.get("global", False)

    return False


class KahluaExposer:
    """
    Simulates how Kahlua's Exposer represents Java classes in Lua.
    """
    def __init__(self, torch: Torch) -> None:
        self.torch: Torch = torch
        self.classes: dict[str, KahluaClass] = {}
        # this class is needed for how Kahlua exposes classes
        self.add_class_by_name("java/lang/Class", VisibilityLevel.VISIBLE)

    def get_valid_name(self, clazz: Class) -> str:
        name = clazz.simple_name()
        if name in self.classes:
            name = clazz.name.replace("/", ".")

        assert name not in self.classes

        return name

    def add_class(self, clazz: Class, visibility_level: VisibilityLevel) -> KahluaClass:
        if clazz.name in self.classes:
            existing_class = self.classes[clazz.name]
            assert existing_class.clazz is clazz, "tried to register two different classes with the same name"
            if visibility_level > existing_class.visibility_level:
                existing_class.visibility_level = visibility_level
                if visibility_level is VisibilityLevel.EXPOSED:
                    existing_class.has_class_table = True

            return existing_class

        name = self.get_valid_name(clazz)

        kahlua_class = KahluaClass(
            clazz,
            name,
            visibility_level,
            visibility_level is VisibilityLevel.EXPOSED
        )
        self.classes[clazz.name] = kahlua_class

        return kahlua_class

    def add_class_by_name(self, name: str, visibility_level: VisibilityLevel) -> KahluaClass:
        clazz = self.torch.get_class(name)
        if clazz is not None:
            return self.add_class(clazz, visibility_level)
        else:
            raise ValueError(f"failed to expose unknown class {name}")

    def expose_referenced_types(self, _type: TypeReference) -> None:
        if _type.is_type_variable:
            return

        if _type.basic not in self.classes and _type.basic not in PRIMITIVE_TYPE_NAMES:
            self.add_class_by_name(
                _type.basic, VisibilityLevel.VISIBLE
            )

        for element in _type.elements:
            for argument in element.type_arguments:
                if argument.type is not None:
                    self.expose_referenced_types(argument.type)

    def expose_supers(self) -> None:
        class_stack: list[KahluaClass] = [
            clazz
            for clazz in self.classes.values()
            if clazz.visibility_level >= VisibilityLevel.VISIBLE
        ]

        while len(class_stack) > 0:
            clazz = class_stack.pop()

            if clazz.visibility_level >= VisibilityLevel.EXPOSED_SUBCLASS:
                child_visibility = VisibilityLevel.EXPOSED_SUBCLASS
            else:
                child_visibility = VisibilityLevel.VISIBLE

            for _supertype in clazz.clazz.get_all_supertypes():
                supertype_name = _supertype.basic
                if supertype_name not in self.classes:
                    super_object = self.torch.get_class(supertype_name)
                    if super_object is not None:
                        kahlua_super = self.add_class(super_object, child_visibility)
                        class_stack.append(kahlua_super)
                    else:
                        print(f"KahluaExposer: could not find supertype {_supertype}")

    def expose_visible_to_method(self, method: Method) -> None:
        for parameter in method.parameters:
            self.expose_referenced_types(parameter.type)

        for parameter in method.type_parameters:
            for bound in parameter.bounds:
                self.expose_referenced_types(bound)

        self.expose_referenced_types(method.returns)

    def expose_all_visible(self) -> None:
        for clazz in list(self.classes.values()):
            torch_class = clazz.clazz

            for _super in torch_class.get_all_supertypes():
                self.expose_referenced_types(_super)

            if not clazz.visibility_level >= VisibilityLevel.EXPOSED_SUBCLASS:
                continue

            for field in torch_class.fields.values():
                self.expose_referenced_types(field.type)

            for cluster in torch_class.methods.values():
                for method in cluster.methods:
                    self.expose_visible_to_method(method)

            for constructor in torch_class.constructors:
                for parameter in constructor.parameters:
                    self.expose_referenced_types(parameter.type)

                for parameter in constructor.type_parameters:
                    for bound in parameter.bounds:
                        self.expose_referenced_types(bound)

            self.expose_enclosing_classes(torch_class)

    def expose_visible_to_globals(self, clazz: Class) -> None:
        for method in clazz.get_all_methods():
            if not is_global_method(method):
                continue

            self.expose_visible_to_method(method)

    def expose_enclosing_classes(self, clazz: Class) -> None:
        for enclosing_class_name in get_enclosing_classes(clazz.name):
            enclosing_class = self.torch.get_class(enclosing_class_name)
            if enclosing_class is not None:
                self.add_class(enclosing_class, VisibilityLevel.INVISIBLE)
            else:
                print(f"KahluaExposer: could not find enclosing class {enclosing_class_name} of {clazz.name}")

    def expose(self, exposed: Iterable[Class]) -> None:
        for clazz in exposed:
            self.add_class(clazz, VisibilityLevel.EXPOSED)

        self.expose_supers()
        self.expose_all_visible()
