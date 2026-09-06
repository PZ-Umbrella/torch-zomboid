import traceback
import zipfile
from collections.abc import Iterable
from pathlib import Path
from operator import attrgetter, itemgetter

from albion.torch import Torch
from albion.torch.filesystem import FileSystem
from albion.torch.types import Method, Class
from albion.torch.rosetta import RosettaContext
from albion.torch.rosetta.reader import load_file
from albion.torch.rosetta.applicator import apply_class
from albion.torch.rosetta.writer import write_to

# this file requires tkinter, so don't import it anywhere unrelated to the editor!
try:
    from tkinter import *  # pyright: ignore[reportWildcardImportFromLibrary]
    from tkinter.ttk import *  # pyright: ignore[reportWildcardImportFromLibrary]
    from tkinter import messagebox
except ImportError:
    print(
        "Tkinter doesn't appear to be installed on your system.\n"
        "On Windows this should be installed by the Python installer unless you turned it off.\n"
        "On Linux the installation varies by distribution, but it's probably on your package manager."
    )
    raise


JAR_PATH = Path("/home/albion/.steam/steam/steamapps/common/ProjectZomboid/projectzomboid/projectzomboid.jar")

ROSETTA_PATH = Path("/home/albion/Modding/Zomboid/pz-rosetta-source/rosetta/java")

ROSETTA_OUT = ROSETTA_PATH


# class SaveWindow():
#     def __init__(self) -> None:
#         self.root: Tk = Tk()
#         self.root.title("Saving...")

#         self.label = Label(self.root)
#         self.label.config(text="Saving to disk...")
#         self.label.grid(column=0, row=0)

#         self.progress_bar: Progressbar = Progressbar(self.root)
#         self.progress_bar.grid(column=0, row=1)
#         self.progress_bar.config(mode="indeterminate")


def show_save_window(clazzes: list[Class]) -> None:
    # TODO: add progressbar showing save progress
    num_errors: int = 0
    for clazz in clazzes:
        try:
            write_to([clazz], Path(ROSETTA_OUT / clazz.package()) / (clazz.simple_name() + ".yml"))
        except Exception as e:
            messagebox.showerror(
                "Rosetta Editor",
                f"Exception occured while saving Rosetta data for class '{clazz.simple_name}'. Your changes to this class have not been saved.\n"
                "Exception details:\n"
                + "".join(traceback.format_exception(e)))
            num_errors += 1

    messagebox.showinfo("Rosetta Editor", f"Save complete. {num_errors} errors occured during saving.")


def get_all_classes(jar_path: Path) -> Iterable[tuple[str, Iterable[str]]]:
    packages: dict[str, list[str]] = {}
    jar = zipfile.ZipFile(jar_path)
    for name in jar.namelist():
        if name.endswith(".class"):
            package, clazz = name.removesuffix(".class").rsplit("/", 1)
            package = package.replace("/", ".")
            if package not in packages:
                packages[package] = []
            packages[package].append(clazz)

    return packages.items()


def get_readable_method_name(method: Method) -> str:
    name = method.returns.type.simple_name() + " " + method.name
    
    if len(method.type_parameters) > 0:
        name = f"<{", ".join(parameter.name for parameter in method.type_parameters)}>"
    name += f"({", ".join(parameter.type.simple_name() for parameter in method.parameters)})"

    # fix any pesky / package separators that remain
    # ideally these would not include package at all but that's hard...
    return name.replace("/", ".")


class ClassFrame:
    def method_selected(self, _) -> None:
        selected_id = self.object_tree.selection()[0]
        selected_method = self.method_by_item[selected_id]

        self.description_entry.config(state="normal")

        self.description_entry.delete(0.0, "end")
        if selected_method.docs is not None:
            self.description_entry.insert(1.0, selected_method.docs.notes)
        
        self.current_method = selected_method

    def rebuild_for_class(self, clazz: Class) -> None:
        # clean up previous class stuff
        self.object_tree.delete(*self.object_tree.get_children())
        self.method_by_item = {}

        methods_id = self.object_tree.insert("", "end", text="methods")
        for method in sorted(clazz.get_all_methods(), key=attrgetter("name")):
            id = self.object_tree.insert(
                methods_id,
                "end",
                text=get_readable_method_name(method),
                tags="method"
            )
            self.method_by_item[id] = method
        # fields_id = self.object_tree.insert("", 0, text="fields")
    
    def text_changed(self, _) -> None:
        if self.current_method is not None:
            assert self.current_method.docs is not None
            self.current_method.docs.notes = self.description_entry.get(1.0, END)

    def __init__(self, parent: Misc) -> None:
        self.current_method: Method | None = None

        # FIXME: for some reason this frame doesn't stretch with the rest of the ui
        class_frame = Frame(parent)
        class_frame.grid(column=2, row=0)
        class_frame.grid_columnconfigure(0, weight=1)
        class_frame.grid_rowconfigure(0, weight=2)
        class_frame.grid_rowconfigure(1, weight=1)
        
        self.object_tree: Treeview = Treeview(class_frame, selectmode="browse")
        self.object_tree.grid(column=0, row=0, sticky=(N, E, S ,W))

        self.object_tree.tag_bind("method", "<<TreeviewSelect>>", self.method_selected)

        self.method_by_item: dict[str, Method] = {}
        """Map of object_tree item id to the methods they correspond to"""

        object_scrollbar = Scrollbar(class_frame, orient="vertical", command=self.object_tree.yview)
        object_scrollbar.grid(column=1, row=0, sticky=(N, S, W))

        self.object_tree.configure(yscrollcommand=object_scrollbar.set)

        self.description_entry: Text = Text(class_frame, height=8)
        self.description_entry.grid(column=0, row=1, columnspan=2, sticky=(N, E, S, W))
        self.description_entry.bind("<KeyRelease>", self.text_changed)
        self.description_entry.config(state="disabled")


class MainFrame:
    def class_selected(self, _) -> None:
        selected_id = self.class_tree.selection()[0]
        selected_class = self.class_tree.item(selected_id, "text")
        selected_package = self.class_tree.item(self.class_tree.parent(selected_id), "text")
        qualified_class = selected_package.replace(".", "/") + "/" + selected_class

        clazz = self.torch.get_class(qualified_class)
        if clazz is None:
            clazz = self.torch.add_class_by_name(qualified_class)
            assert clazz is not None, f"Failed to parse class {qualified_class}"

            sanitised_class = selected_class.replace("$", ".")

            rosetta_file = ROSETTA_PATH / Path(selected_package.replace(".", "/")) / (sanitised_class + ".yml")
            if rosetta_file.is_file():
                rosetta: RosettaContext = load_file(rosetta_file)
                if selected_package in rosetta and sanitised_class in rosetta[selected_package]:
                    apply_class(clazz, rosetta[selected_package][sanitised_class])
                else:
                    print(f"WEIRD: Rosetta file exists but doesn't contain the correct class '{qualified_class}'")
            else:
                print("no rosetta")

        self.class_frame.rebuild_for_class(clazz)


    def populate_class_tree(self) -> None:
        for package in sorted(get_all_classes(JAR_PATH), key=itemgetter(0)):
            package_id = self.class_tree.insert("", "end", text=package[0])
            for clazz in sorted(package[1]):
                class_id = self.class_tree.insert(
                    package_id,
                    "end",
                    text=clazz,
                    tags="class"
                )
        
        self.class_tree.tag_bind("class", "<<TreeviewSelect>>", self.class_selected)

    def save_changes(self) -> None:
        clazzes: list[Class] = []
        for package in self.torch.packages.values():
            clazzes.extend(package.classes.values())
        show_save_window(clazzes)

    def __init__(self, frame_parent: Misc) -> None:
        self.filesystem: FileSystem = FileSystem([JAR_PATH])
        self.torch: Torch = Torch(self.filesystem)

        main_frame = Frame(frame_parent, padding=(3, 3, 12, 12))
        main_frame.pack(expand=True, fill="both")
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(0, weight=1)

        editor_frame = Frame(main_frame)
        editor_frame.grid(column=0, row=0, sticky=(N, E, S, W))
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        editor_frame.columnconfigure(2, weight=3)

        self.class_tree: Treeview = Treeview(editor_frame, selectmode="browse")
        self.class_tree.grid(column=0, row=0, sticky=(N, E, S, W))

        class_scrollbar = Scrollbar(editor_frame, orient="vertical", command=self.class_tree.yview)
        class_scrollbar.grid(column=1, row=0, sticky=(N, E, S))

        self.class_tree.configure(yscrollcommand=class_scrollbar.set)

        self.populate_class_tree()

        self.class_frame = ClassFrame(editor_frame)
        
        save_button = Button(main_frame, text="Write changes to disk", command=self.save_changes)
        save_button.grid(column=0, row=1, sticky=(N, E, S))


def main() -> None:
    root = Tk()
    root.title("Rosetta Editor")

    main_frame = MainFrame(root)

    root.mainloop()


if __name__ == "__main__":
    main()
