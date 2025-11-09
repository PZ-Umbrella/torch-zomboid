import typing
from typing import NamedTuple

import kirjava
from kirjava import InsnBlock, JumpEdge, MethodInfo, FallthroughEdge
from kirjava.analysis import InsnEdge
from kirjava.instructions import InvokeInstruction, ConstantInstruction, UnaryComparisonJumpInstruction, NewInstruction

from albion.torch import FileSystem


LOAD_CONSTANT_INSTRUCTIONS = {"ldc", "ldc_w"}
INVOKE_INSTRUCTIONS = {"invokedynamic", "invokeinterface", "invokespecial", "invokestatic", "invokevirtual"}


class ExposedClassDiscoverer:
    class Result(NamedTuple):
        classes: set[str]
        """Classes that are exposed."""
        globals_classes: set[str]
        """Classes that have their globals exposed."""

    def __init__(self) -> None:
        self.exposer_methods: set[tuple[str, str]] = set()
        self.exposed_classes: set[str] = set()
        self.exposed_globals_classes: set[str] = set()

    def add_classes_exposed_by_method(self, method: MethodInfo):
        graph = kirjava.disassemble(method)

        # we detect exposed classes by assuming that the most recently pushed class is at the top of the stack
        recent_class = None
        # most recent type pushed onto the stack, probably (the detection for this is very primitive)
        recent_object_type = None
        block_stack: list[InsnBlock] = [graph.entry_block]
        while len(block_stack) > 0:
            block = block_stack.pop()

            for instruction in block.instructions:
                if instruction.mnemonic in LOAD_CONSTANT_INSTRUCTIONS:
                    instruction = typing.cast(ConstantInstruction, instruction)
                    if instruction.constant.type.name == "java/lang/Class":
                        assert isinstance(instruction.constant, kirjava.constants.Class)
                        recent_class = instruction.constant.class_type.name
                elif instruction.mnemonic == "new":
                    instruction = typing.cast(NewInstruction, instruction)
                    recent_object_type = instruction.type.name
                elif instruction.mnemonic in INVOKE_INSTRUCTIONS:
                    instruction = typing.cast(InvokeInstruction, instruction)
                    if instruction.reference.name == "setExposed":
                        class_name = instruction.reference.class_.name
                        if class_name == "zombie/Lua/LuaManager$Exposer":
                            assert recent_class is not None
                            self.exposed_classes.add(
                                recent_class.replace("$", ".")
                            )
                            recent_class = None
                        else:
                            self.exposer_methods.add(
                                (class_name, "setExposed")
                            )
                    elif instruction.reference.name == "exposeGlobalFunctions" \
                            and instruction.reference.class_.name == "zombie/Lua/LuaManager$Exposer":
                        assert recent_object_type is not None
                        self.exposed_globals_classes.add(
                            recent_object_type.replace("$", ".")
                        )

            for edge in graph.out_edges(block):
                if isinstance(edge, InsnEdge) and edge.instruction is not None:
                    if isinstance(edge, JumpEdge):
                        if isinstance(edge.instruction, UnaryComparisonJumpInstruction):
                            match edge.instruction.comparison:
                                # skip every conditional block
                                # there should probably be more complex logic for this,
                                # but this is really all we need
                                case UnaryComparisonJumpInstruction.EQ:
                                    block_stack.append(edge.to)
                                    break
                                case _:
                                    continue
                elif isinstance(edge, FallthroughEdge):
                    block_stack.append(edge.to)

    @staticmethod
    def get_exposed_classes_recurse(filesystem: FileSystem, class_name: str, method_name: str) -> Result:
        discoverer = ExposedClassDiscoverer()
        discoverer.exposer_methods.add((class_name, method_name))

        while len(discoverer.exposer_methods) > 0:
            clazz_name, method = discoverer.exposer_methods.pop()
            clazz_path = filesystem.find_class_file(clazz_name)
            with clazz_path.open('rb') as file:
                clazz = kirjava.load(file)

            discoverer.add_classes_exposed_by_method(clazz.get_method(method))

        return ExposedClassDiscoverer.Result(discoverer.exposed_classes, discoverer.exposed_globals_classes)

