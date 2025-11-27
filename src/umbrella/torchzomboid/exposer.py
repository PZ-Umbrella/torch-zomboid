import enum

from collections.abc import Iterable
from dataclasses import dataclass

from albion.torch import Torch
from albion.torch.types import Class, TypeReference, Method
from albion.torch.util import OrderedEnum

from umbrella.torchzomboid import KAHLUA_METHOD_ANNOTATION


class VisibilityLevel(OrderedEnum):
    NONE = enum.auto()
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


def is_global_method(method: Method) -> bool:
    annotation = method.get_annotation(KAHLUA_METHOD_ANNOTATION)
    if annotation is not None:
        return annotation.arguments.get("global", False)

    return False


class KahluaExposer:
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
            cached_class = self.classes[clazz.name]
            assert cached_class.clazz == clazz, "tried to register two different classes with the same name"
            if visibility_level > cached_class.visibility_level:
                cached_class.visibility_level = visibility_level

            return cached_class

        name = self.get_valid_name(clazz)

        kahlua_class = KahluaClass(clazz, name, visibility_level)
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

        if _type.basic not in self.classes and _type.basic not in PRIMITIVE_TYPES:
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
            self.expose_referenced_types(parameter)

        for parameter in method.type_parameters:
            for bound in parameter.bounds:
                self.expose_referenced_types(bound)

        self.expose_referenced_types(method.returns)

    def expose_all_visible(self) -> None:
        for clazz in list(self.classes.values()):
            clazz_object = clazz.clazz

            for _super in clazz_object.get_all_supertypes():
                self.expose_referenced_types(_super)

            if not clazz.visibility_level >= VisibilityLevel.EXPOSED_SUBCLASS:
                continue

            for field in clazz_object.fields.values():
                self.expose_referenced_types(field.type)

            for cluster in clazz_object.methods.values():
                for method in cluster.methods:
                    self.expose_visible_to_method(method)

            for constructor in clazz_object.constructors:
                for parameter in constructor.parameters:
                    self.expose_referenced_types(parameter)

                for parameter in constructor.type_parameters:
                    for bound in parameter.bounds:
                        self.expose_referenced_types(bound)

    def expose_visible_to_globals(self, clazz: Class) -> None:
        for method in clazz.get_all_methods():
            if not is_global_method(method):
                continue

            self.expose_visible_to_method(method)

    def expose(self, exposed: Iterable[Class]) -> None:
        for clazz in exposed:
            self.add_class(clazz, VisibilityLevel.EXPOSED)

        self.expose_supers()
        self.expose_all_visible()
