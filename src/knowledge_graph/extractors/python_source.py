"""AST lookup syntax, deliberately not alias analysis or consumption proof."""
import ast
import json


def lookup(node):
    if isinstance(node, ast.Name):
        return (("name", node.id),)
    if isinstance(node, ast.Attribute):
        base = lookup(node.value)
        return base + (("attribute", node.attr),) if base else None
    if isinstance(node, ast.Subscript):
        base, key = lookup(node.value), node.slice
        operation = "subscript"
    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
          and node.func.attr == "get" and node.args):
        base, key = lookup(node.func.value), node.args[0]
        operation = "get"
    else:
        return None
    if base and isinstance(key, ast.Constant) and isinstance(key.value, str):
        return base + ((operation, key.value),)
    return None


def parse(result, path, text):
    tree = ast.parse(text)
    root = result.entity(path, "module", "PythonSymbol", "module")
    conditional = any(isinstance(n, (ast.If, ast.IfExp, ast.For, ast.While,
                      ast.Try, ast.Match, ast.comprehension)) for n in ast.walk(tree))
    condition = {"state": "unresolved", "expression": ""} if conditional else None
    if conditional:
        result.coverage(path, "unresolved", "python_control_flow_not_evaluated")

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.owner = root
            self.anchor = "module"

        def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            old, anchor = self.owner, self.anchor
            self.anchor = anchor + "/" + node.name + ":" + str(node.lineno)
            self.owner = result.entity(path, self.anchor, "PythonSymbol", node.name, node.lineno)
            self.generic_visit(node)
            self.owner, self.anchor = old, anchor

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

        def emit(self, node):
            occurrence = json.dumps([node.lineno, node.col_offset,
                                     node.end_lineno, node.end_col_offset])
            segments = lookup(node)
            if segments:
                # A source-local syntactic field reference, not a resolved profile alias.
                label = ".".join(value.replace("\\", "\\\\").replace(".", "\\.")
                                 for _, value in segments[1:])
                field = result.entity(path, [self.anchor, "lookup", segments],
                                      "ProfileField", label, node.lineno)
                result.claim(self.owner, "references_field", field, path, node.lineno,
                             node.end_lineno, occurrence=occurrence, condition=condition,
                             iri=True)
            else:
                result.claim(self.owner, "unresolved_reference", "dynamic_lookup", path,
                             node.lineno, node.end_lineno, assessment="unreviewed",
                             condition={"state": "unresolved", "expression": ""},
                             occurrence=occurrence)
                result.coverage(path, "unresolved", "python_dynamic_lookup")

        def visit_Subscript(self, node):
            self.emit(node)
            self.generic_visit(node)

        def visit_Call(self, node):
            if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                self.emit(node)
            self.generic_visit(node)

    Visitor().visit(tree)
