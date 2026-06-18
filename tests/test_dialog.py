"""Unit tests for the add-in dialog logic, with `adsk` mocked so they run under
pytest (no Fusion). Covers the lossless build->read round-trip, preset autofill,
and the parameter-insert (autofill/suggestion) helper.
"""

import os
import sys
import types

import pytest

# --- inject a fake `adsk.core` so dialog.py (and its sibling import path) load ---
_adsk = types.ModuleType("adsk")
_core = types.ModuleType("adsk.core")


class _Styles:
    TextListDropDownStyle = 0


_core.DropDownStyles = _Styles
_core.CommandInputs = object
_adsk.core = _core
sys.modules.setdefault("adsk", _adsk)
sys.modules.setdefault("adsk.core", _core)

# make the add-in folder importable (for `import dialog`)
_ADDIN = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                      "eqcurve", "addin", "EquationCurve")
sys.path.insert(0, _ADDIN)

import dialog  # noqa: E402
from eqcurve.core import CurveDef  # noqa: E402


# --- a minimal CommandInputs mock --------------------------------------------

class _Item:
    def __init__(self, name, sel):
        self.name = name
        self.isSelected = sel


class _ListItems:
    def __init__(self):
        self._items = []

    def add(self, name, sel):
        it = _Item(name, sel)
        self._items.append(it)
        return it

    def __iter__(self):
        return iter(self._items)

    def item(self, i):
        return self._items[i]


class _Dropdown:
    def __init__(self):
        self.listItems = _ListItems()

    @property
    def selectedItem(self):
        for it in self.listItems._items:
            if it.isSelected:
                return it
        return None


class _Value:
    def __init__(self, value):
        self.value = value


class _Group:
    def __init__(self, children):
        self.isExpanded = True
        self.children = children


class _Selection:
    def __init__(self):
        self.selectionCount = 0

    def addSelectionFilter(self, _f):
        pass

    def setSelectionLimits(self, _a, _b=0):
        pass


class MockInputs:
    def __init__(self):
        self._by = {}

    def addDropDownCommandInput(self, _id, _name, _style):
        self._by[_id] = _Dropdown()
        return self._by[_id]

    def addStringValueInput(self, _id, _name, value):
        self._by[_id] = _Value(value)
        return self._by[_id]

    def addIntegerSpinnerCommandInput(self, _id, _name, _mn, _mx, _step, value):
        self._by[_id] = _Value(value)
        return self._by[_id]

    def addBoolValueInput(self, _id, _name, _b, _s, value):
        self._by[_id] = _Value(value)
        return self._by[_id]

    def addTextBoxCommandInput(self, _id, _name, text, _rows, _ro):
        self._by[_id] = _Value(text)
        return self._by[_id]

    def addGroupCommandInput(self, _id, _name):
        self._by[_id] = _Group(MockInputs())
        return self._by[_id]

    def addSelectionInput(self, _id, _name, _prompt):
        self._by[_id] = _Selection()
        return self._by[_id]

    def itemById(self, _id):
        return self._by.get(_id)


class _Changed:
    def __init__(self, _id):
        self.id = _id


# --- tests -------------------------------------------------------------------

def test_build_read_roundtrip_is_lossless():
    cd = CurveDef(
        mode="parametric", coord="cylindrical", dim=3,
        exprs={"r": "R0 + t", "theta": "t", "z": "2*t"}, var="t",
        t_min="0", t_max="6*pi", samples=240, closed=False,
        adaptive=True, tolerance=0.01,
        origin={"x": "1", "y": "2", "z": "3"},
        rotation={"x": "0", "y": "0", "z": "30"},
    )
    mi = MockInputs()
    dialog.build_inputs(mi, cd, ["R0"])
    got = dialog.read_inputs(mi)
    for field in ("mode", "coord", "dim", "angle", "exprs", "var",
                  "t_min", "t_max", "samples", "closed", "adaptive",
                  "tolerance", "origin", "rotation"):
        assert getattr(got, field) == getattr(cd, field), field


def test_preset_autofills_fields():
    mi = MockInputs()
    dialog.build_inputs(mi, None, [])
    pre = mi.itemById("preset")
    for it in pre.listItems:
        it.isSelected = (it.name == "Cardioid")
    dialog.on_input_changed(mi, _Changed("preset"))
    got = dialog.read_inputs(mi)
    assert got.coord == "polar" and got.closed is True
    assert "cos" in got.exprs["r"]


def test_parameter_insert_appends_to_last_field():
    mi = MockInputs()
    dialog.build_inputs(mi, None, ["D3", "N"])
    # user last edited the y field, which already has content ending in ')'
    dialog.on_input_changed(mi, _Changed("ey"))
    mi.itemById("ey").value = "sin(t)"
    ins = mi.itemById("param_insert")
    for it in ins.listItems:
        it.isSelected = (it.name == "D3")
    dialog.on_input_changed(mi, _Changed("param_insert"))
    assert mi.itemById("ey").value.endswith("D3")          # inserted
    assert ins.listItems.item(0).isSelected is True        # dropdown reset


def test_help_group_present():
    mi = MockInputs()
    dialog.build_inputs(mi, None, [])
    assert mi.itemById("help") is not None
    assert mi.itemById("param_insert") is not None
