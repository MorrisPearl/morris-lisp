"""The libraries (lib/) and the example programs (examples/) all define their names in the one global environment
of a notebook. So a library that defines a name the interpreter already has replaces that builtin for everyone
who uses the library afterwards, and an example that defines a library's name changes the library for whoever
runs the example in the same notebook. These tests read every file's top-level definitions and check that
neither happens."""

from support import *


def defined_names(path):
    """The names that the top-level forms of a Lisp file define: by define, defmacro, defgeneric, and
    defstruct (which defines make-NAME, NAME?, copy-NAME, and NAME-SLOT and NAME-SLOT-set! for its own slots).
    A list, with a name as often as it is defined. (defmethod adds to a generic function, so it isn't counted.)"""
    Symbol, Pair = lisp_core.Symbol, lisp_core.Pair
    with open(path, encoding="utf-8") as f:
        forms = list(lisp_core.parse(f.read()))
    names = []
    for form in forms:
        if not (isinstance(form, Pair) and isinstance(form.cdr, Pair)):
            continue
        head, target = form.car, form.cdr.car
        if head in (Symbol("define"), Symbol("defmacro"), Symbol("defgeneric")):
            names.append(str(target.car if isinstance(target, Pair) else target))
        elif head == Symbol("defstruct"):
            struct_name = str(target.car if isinstance(target, Pair) else target)
            names += ["make-" + struct_name, struct_name + "?", "copy-" + struct_name]
            for slot in lisp_core.pairs_to_list(form.cdr.cdr):
                slot_name = str(slot.car if isinstance(slot, Pair) else slot)
                names += [struct_name + "-" + slot_name, struct_name + "-" + slot_name + "-set!"]
    return names


def lisp_files(directory):
    return sorted(os.path.join(directory, name) for name in os.listdir(directory) if name.endswith(".lsp"))


class TestNamesDontCollide(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        env = lisp_builtins.make_global_env(output=lambda text: None)     # the builtins and standard macros, no libraries
        cls.builtins = {str(name) for name in env.keys()}
        cls.library_names = {path: defined_names(path) for path in lisp_files(LIB)}
        cls.example_names = {path: defined_names(path) for path in lisp_files(EXAMPLES)}

    def test_no_library_or_example_redefines_a_builtin(self):
        clashes = ["%s defines %s" % (os.path.relpath(path, HERE), name)
                   for files in (self.library_names, self.example_names)
                   for path, names in files.items() for name in names if name in self.builtins]
        self.assertEqual(clashes, [], "these replace a builtin of the same name")

    def test_no_name_is_defined_twice_in_the_libraries(self):
        where = {}
        for path, names in self.library_names.items():
            for name in names:
                where.setdefault(name, []).append(os.path.basename(path))
        twice = {name: files for name, files in where.items() if len(files) > 1}
        self.assertEqual(twice, {}, "a name defined twice: the later definition replaces the earlier one")

    def test_no_example_redefines_a_library_name(self):
        library = {name: os.path.basename(path) for path, names in self.library_names.items() for name in names}
        clashes = ["%s defines %s, which %s defines" % (os.path.basename(path), name, library[name])
                   for path, names in self.example_names.items() for name in names if name in library]
        self.assertEqual(clashes, [], "running these examples would change a library")


if __name__ == "__main__":
    unittest.main()
