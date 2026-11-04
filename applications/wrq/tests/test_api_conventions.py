"""Protocol regression: static GET query paths and POST JSON/form bodies."""
import ast
from pathlib import Path


def test_changed_routes_only_use_get_post_and_no_path_identifiers():
    root = Path(__file__).resolve().parents[3]
    files = list((root / 'applications/wrq/agent/views').glob('*.py'))
    files += [root / 'applications/knowledge_base/views/platform_view.py',
              root / 'applications/knowledge_base/views/conversion_view.py']
    count = 0
    for path in files:
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for function in ast.walk(tree):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in function.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr
                if method not in {'get', 'post', 'put', 'delete', 'patch'}:
                    continue
                count += 1
                assert method in {'get', 'post'}, (path, function.name, method)
                route = ast.literal_eval(decorator.args[0])
                assert '{' not in route, (path, route)
                if method == 'post':
                    assert not any(isinstance(value, ast.Call) and getattr(value.func, 'id', None) == 'Query'
                                   for value in function.args.defaults), (path, function.name)
    assert count >= 30
