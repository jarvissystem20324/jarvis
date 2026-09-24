"""Reading tracebacks: finding the frames that are actually yours."""

from __future__ import annotations

from jarvis import trace

PYTHON_TB = '''Traceback (most recent call last):
  File "C:\\Python314\\Lib\\site-packages\\flask\\app.py", line 1500, in dispatch
    return handler()
  File "{root}/src/calc.py", line 2, in add
    return a - b
ZeroDivisionError: division by zero
'''

JS_TB = '''TypeError: Cannot read properties of undefined (reading 'x')
    at add (/home/ci/build/src/calc.js:2:10)
    at Object.<anonymous> (/home/ci/build/node_modules/jest/run.js:40:3)
'''


def test_python_frames_are_found():
    found = trace.frames(PYTHON_TB.format(root="/p"))
    assert [(f.line, f.func) for f in found] == [(1500, "dispatch"), (2, "add")]


def test_javascript_frames_are_found():
    found = trace.frames(JS_TB)
    assert found[0].file.endswith("src/calc.js") and found[0].line == 2
    assert found[0].func == "add"


def test_the_error_line_is_the_real_error():
    assert trace.error_line(PYTHON_TB.format(root="/p")) == "ZeroDivisionError: division by zero"
    assert trace.error_line(JS_TB).startswith("TypeError")


def test_library_frames_are_not_treated_as_yours(project):
    error, ours = trace.analyse(PYTHON_TB.format(root=str(project).replace("\\", "/")), project)
    assert [f.line for f in ours] == [2]
    assert "site-packages" not in ours[0].label()


def test_the_failing_line_is_read_and_marked(project):
    _error, ours = trace.analyse(PYTHON_TB.format(root=str(project).replace("\\", "/")), project)
    assert ">>    2 |     return a - b" in ours[0].code


def test_a_path_from_another_machine_is_matched_by_its_tail(project):
    """A CI traceback says /home/ci/build/src/calc.py; here it is src/calc.py."""
    (project / "src" / "calc.js").write_text("function add(a,b){\n  return a.x\n}\n", encoding="utf-8")
    _error, ours = trace.analyse(JS_TB, project)
    assert ours and ours[0].resolved == project / "src" / "calc.js"


def test_no_project_frames_means_nothing_is_read(project):
    tb = 'File "/usr/lib/python3/site-packages/x.py", line 1\nValueError: bad\n'
    _error, ours = trace.analyse(tb, project)
    assert ours == []
