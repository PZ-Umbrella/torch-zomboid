import shutil
import json
import sys

from pathlib import Path
from argparse import ArgumentParser
from collections.abc import Iterable

from albion.torch import Torch
from albion.torch.types import Class
from albion.torch.filesystem import FileSystem
from umbrella.torchzomboid import get_enclosing_classes
from umbrella.torchzomboid.discovery import ExposedClassDiscoverer
from albion.torch.rosetta.reader import load_dir_recurse
from albion.torch.rosetta.applicator import apply_rosetta
from albion.torch.rosetta.writer import write_to

from umbrella.torchzomboid.writer import write_all


def get_game_classpath(game_path: Path) -> list[Path]:
    config_path = game_path / "ProjectZomboid64.json"
    if not config_path.is_file():
        return [game_path]

    with config_path.open('r', encoding="utf-8") as file:
        config = json.load(file)

    if "classpath" not in config:
        return [game_path]

    classpath = []
    for path in config["classpath"]:
        classpath.append(game_path / path)

    return classpath


def extract_jdk(jdk_path: Path, out_path: Path) -> None:
    if out_path.is_dir():
        return
    
    import subprocess
    import os

    if "JAVA_HOME" not in os.environ:
        print(
            "JDK not detected on your system, cannot dump automatically.\n"
            "Expect missing class file errors and incomplete output.\n"
            "Ensure that Java 25 or above is installed.\n"
            "You can also provide a dump of the JDK created by jimage with the --jdk option."
        )
        return

    # TODO: we should probably check if it is java 25 or newer somehow

    executable_name = "jimage" if sys.platform != "win32" else "jimage.exe"

    print("Dumping JDK, this may take some time...")
    subprocess.run(
        [
            Path(os.environ["JAVA_HOME"], "bin", executable_name),
            "extract",
            f"--dir={out_path}", jdk_path
        ]
    )


def get_jdk_paths(game_path: Path, jdk_path: Path) -> list[Path]:
    paths: list[Path] = []

    extract_jdk(game_path / "jre64/lib/modules", jdk_path)
    if not jdk_path.is_dir():
        print(
            "Failed to automatically dump the JDK: "
            "Expect missing class file errors and incomplete output.\n"
            "To prevent this, provide a dump of the JDK created by jimage with the --jdk option."
        )

    if jdk_path.is_dir():
        for path in jdk_path.iterdir():
            paths.append(path)

    return paths


def main() -> None:
    parser = ArgumentParser(
        "Torch",
        description="Writes information about Project Zomboid's Java types in various formats.",
        allow_abbrev=False
    )
    parser.add_argument(
        "language",
        choices=["emmylua", "rosetta", "luacats"],
        help="type of files to generate"
    )
    parser.add_argument(
        "game_path",
        type=Path,
        help="path to a Project Zomboid installation. On Linux, both the ProjectZomboid and ProjectZomboid/projectzomboid directories are acceptable."
    )
    parser.add_argument(
        "out_path",
        type=Path,
        help="directory to write output files to"
    )
    parser.add_argument(
        "--rosetta",
        type=Path,
        help="path to Rosetta data to provide documentation for the discovered types"
    )
    parser.add_argument(
        "--jdk",
        type=Path,
        help="path to a JDK dumped with jimage.\n"
             "The JDK will be dumped to this path if it does not already exist.\n"
             "If this fails, you can dump it yourself and place it at this path.",
        default=Path("./temp/jdk")
    )

    args = parser.parse_args()

    game_path: Path = args.game_path
    if sys.platform == "linux" and game_path.name == "ProjectZomboid":
        game_path = game_path / "projectzomboid"
    assert game_path.is_dir()

    filesystem = FileSystem(get_jdk_paths(game_path, args.jdk) + get_game_classpath(game_path))

    print("Discovering types...")

    exposed = ExposedClassDiscoverer.get_exposed_classes_recurse(
        filesystem,
        "zombie/Lua/LuaManager.Exposer", "exposeAll"
    )

    enclosing_classes: set[str] = set()
    for clazz in exposed.classes:
        enclosing_classes.update(get_enclosing_classes(clazz))

    print("Building type information...")

    torch = Torch(filesystem)

    # needed for the lua renderer
    torch.add_class_by_name_recurse("java/lang/Class")
    torch.add_classes_by_name_recurse(exposed.classes | exposed.globals_classes | enclosing_classes)

    rosetta_path: Path = args.rosetta
    if rosetta_path is not None and rosetta_path.is_dir():
        print("Loading input Rosetta files...")
        packages = load_dir_recurse(rosetta_path)
        apply_rosetta(torch, packages)

    match args.language:
        case "emmylua":
            print("Writing EmmyLua...")
            exposed_classes = [torch.get_class(clazz) for clazz in exposed.classes]
            assert None not in exposed_classes
            exposed_globals = [torch.get_class(clazz) for clazz in exposed.globals_classes]
            assert None not in exposed_globals

            write_emmylua(torch, args.out_path, exposed_classes, exposed_globals)  # pyright: ignore[reportArgumentType]
        case "luacats":
            write_luacats()
        case "rosetta":
            print("Writing Rosetta...")
            write_rosetta(torch, args.out_path)


def write_emmylua(torch: Torch, path: Path, exposed: Iterable[Class], exposed_globals: Iterable[Class]) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)

    write_all(torch, path, exposed, exposed_globals)


def write_rosetta(torch: Torch, path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)

    for package in torch.packages.values():
        package_path = path / package.name
        for clazz in package.classes.values():
            write_to([clazz], package_path / (clazz.simple_name() + ".yml"))


def write_luacats() -> None:
    # TODO
    print("LuaCATS is not implemented yet.")


if __name__ == "__main__":
    main()
